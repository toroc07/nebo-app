"""Nebo HTTP API. Run from the backend folder with: uvicorn app.main:app --reload"""

from __future__ import annotations

from dataclasses import asdict
import io
import logging
from typing import Any, Literal

import numpy as np

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import config, db, ephemeris, imaging, irsa, metrics, models, science_catalogs
from .service import (
    ServiceBusy,
    TargetNotFound,
    TimelineService,
    TimelineView,
    datetime_to_mjd,
)
from .store import Patch, Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

API_PREFIX = "/api/v1"
RETRY_AFTER_S = 5
BUSY_RETRY_AFTER_S = 30
DEFAULT_DETECTOR = 3
SizeName = Literal["small", "medium", "large"]

app = FastAPI(
    title="Nebo API",
    version="0.2.0",
    description=(
        "SPHEREx image timelines for any patch of sky, processed and stored in PostgreSQL "
        "for a planetarium-style frontend."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Diff-Limit"],
)


@app.exception_handler(db.DatabaseNotConfigured)
def database_not_configured(_: Request, error: db.DatabaseNotConfigured) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "database_not_configured", "detail": str(error)},
    )


@app.exception_handler(ServiceBusy)
def service_busy(_: Request, __: ServiceBusy) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"code": "busy", "detail": "Too many patches are being built. Retry later."},
        headers={"Retry-After": str(BUSY_RETRY_AFTER_S)},
    )


def get_store() -> Store:
    return db.get_store()


_service: TimelineService | None = None


def get_service(store: Store = Depends(get_store)) -> TimelineService:
    """One service per process: it owns the background build and download thread pools."""
    global _service
    if _service is None or _service.store is not store:
        _service = TimelineService(store)
    return _service


# ----- payloads ---------------------------------------------------------------------------

DATA_SOURCE = "NASA/IPAC IRSA SPHEREx spectral images"


def _epoch_releases(exposures: list[dict], image) -> list[str]:
    """Data releases (e.g. "qr2") of the exposures that make up one epoch."""
    low, high = datetime_to_mjd(image.start_utc), datetime_to_mjd(image.end_utc)
    return sorted({e["release"] for e in exposures if low - 1e-4 <= e["mjd_start"] <= high + 1e-4})


def _sector_payload(patch: Patch, size: str) -> dict:
    """Centre and 4 corners of the image in ICRS degrees (the centre is the central pixel)."""
    sector = imaging.compute_sector_coordinates(patch.ra, patch.dec, size, config.SIZES_DEG[size])
    return {
        "center": {"ra": sector["center_ra_deg"], "dec": sector["center_dec_deg"]},
        "corners": sector["corners_icrs"],
    }


def _expected_position(patch: Patch, target: dict | None, mid_mjd: float, size: str) -> dict | None:
    """Where the catalogue object should be at ``mid_mjd``: sky position and PNG pixel."""
    if not target or target.get("pm_ra_mas_yr") is None or target.get("pm_dec_mas_yr") is None:
        return None
    ra, dec = ephemeris.expected_position(
        patch.ra, patch.dec, target["pm_ra_mas_yr"], target["pm_dec_mas_yr"], mid_mjd
    )
    wcs, (side, _) = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[size])
    x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
    y = side - 1 - y  # FITS row 0 is the bottom; the PNG is flipped.
    return {
        "ra": round(ra, 7),
        "dec": round(dec, 7),
        "x": round(x, 2),
        "y": round(y, 2),
        "in_image": bool(0 <= x <= side - 1 and 0 <= y <= side - 1),
    }


def _patch_payload(patch: Patch) -> dict:
    return {"id": patch.id, "ra": patch.ra, "dec": patch.dec, "target": patch.target_slug}


def _detector_payload(detector: int) -> dict:
    return {
        "id": detector,
        "bandpass": irsa.bandpass_name(detector),
        "wavelength_range_um": list(irsa.DETECTOR_WAVELENGTH_RANGE_UM[detector]),
    }


def _epochs_payload(view: TimelineView, size: str, store: Store) -> list[dict]:
    if not view.images:
        return []
    exposures = store.list_nasa_sector_exposures(view.patch.id, detector=view.detector)
    target = store.get_target(view.patch.target_slug) if view.patch.target_slug else None
    return [
        {
            "index": image.epoch_index,
            "start_utc": image.start_utc.isoformat(),
            "end_utc": image.end_utc.isoformat(),
            "mid_mjd": round(image.mid_mjd, 5),
            "frames_available": image.frames_available,
            "frames_used": image.frames_used,
            "display_min": image.display_min,
            "display_max": image.display_max,
            "releases": _epoch_releases(exposures, image),
            "expected_position": _expected_position(view.patch, target, image.mid_mjd, size),
            "image_url": f"{API_PREFIX}/images/{image.id}.png",
            **({"npz_url": f"{API_PREFIX}/images/{image.id}.npz"} if image.has_npz else {}),
        }
        for image in view.images
    ]


def _timeline_meta_payload(
    view: TimelineView, size: str, side_px: int | None, epochs: list[dict]
) -> dict:
    timeline = view.timeline
    return {
        "size": {
            "name": size,
            "side_deg": config.SIZES_DEG[size],
            "side_arcmin": round(config.SIZES_DEG[size] * 60, 2),
            "width_px": side_px,
            "height_px": side_px,
            "pixel_scale_arcsec": config.PIXEL_SCALE_ARCSEC,
        },
        "orientation": "north_up_east_left",
        "sector": _sector_payload(view.patch, size),
        "display": {
            "stretch": "asinh",
            "unit": "MJy/sr",
            "note": "Zodiacal light subtracted; pixels without data are transparent.",
        },
        "epochs": epochs,
        "frames_found": timeline.frames_found,
        "frames_used": timeline.frames_used,
        "updated_at": timeline.updated_at.isoformat(),
    }


def timeline_payload(view: TimelineView, size: str, store: Store) -> dict:
    base = {
        "status": view.status,
        "patch": _patch_payload(view.patch),
        "detector": _detector_payload(view.detector),
    }
    timeline = view.timeline
    if view.status == "failed":
        return base | {"error": timeline.error}

    epochs = _epochs_payload(view, size, store)
    if view.status == "building":
        side_px = (
            view.images[0].width_px
            if view.images
            else imaging.grid_pixels(config.SIZES_DEG[size])
        )
        return base | {
            **_timeline_meta_payload(view, size, side_px, epochs),
            "is_partial": True,
            "preview_image_url": epochs[0]["image_url"] if epochs else None,
            "progress": {
                "stage": timeline.stage,
                "done": timeline.progress_done,
                "total": timeline.progress_total,
                "epochs_ready": len(epochs),
                "is_partial": True,
            },
            "retry_after_s": RETRY_AFTER_S,
        }

    side_px = view.images[0].width_px if view.images else None
    return base | {
        **_timeline_meta_payload(view, size, side_px, epochs),
        "data": {"source": DATA_SOURCE, "processed_at": timeline.updated_at.isoformat()},
    }


# ----- routes -----------------------------------------------------------------------------


@app.get(f"{API_PREFIX}/health")
def health() -> dict:
    """API liveness plus database state: "ok", "not_configured" or "unreachable"."""
    try:
        db.get_store().ping()
        database = "ok"
    except db.DatabaseNotConfigured:
        database = "not_configured"
    except Exception:
        logging.getLogger(__name__).warning("Database ping failed", exc_info=True)
        database = "unreachable"
    return {"status": "ok", "database": database}


@app.get(f"{API_PREFIX}/targets")
def list_targets(store: Store = Depends(get_store)) -> list[dict]:
    """Catalogue objects to show as markers in the planetarium."""
    return store.list_targets()


@app.get(f"{API_PREFIX}/patches")
def list_patches(store: Store = Depends(get_store)) -> list[dict]:
    """Patches that already have at least one ready timeline (open instantly)."""
    return store.list_patches_with_data()


def _resolve(
    service: TimelineService, ra: float | None, dec: float | None, target: str | None, detector: int | None
) -> tuple[Patch, int]:
    """Patch and detector of a request given as ra/dec or a catalogue target."""
    if target is not None and (ra is not None or dec is not None):
        raise HTTPException(status_code=422, detail="Give either target or ra and dec, not both.")
    if target is None and (ra is None or dec is None):
        raise HTTPException(status_code=422, detail="Give ra and dec, or a target.")
    try:
        patch = service.resolve_patch(ra=ra, dec=dec, target_slug=target)
    except TargetNotFound:
        raise HTTPException(status_code=404, detail=f"Unknown target '{target}'.") from None
    if detector is None:
        catalogue = service.store.get_target(patch.target_slug) if patch.target_slug else None
        detector = catalogue["recommended_detector"] if catalogue else DEFAULT_DETECTOR
    return patch, detector


@app.get(f"{API_PREFIX}/timeline")
def get_timeline(
    ra: float | None = Query(None, ge=0.0, lt=360.0, description="Right ascension, ICRS degrees."),
    dec: float | None = Query(None, ge=-90.0, le=90.0, description="Declination, ICRS degrees."),
    target: str | None = Query(
        None, pattern=r"^[a-z0-9-]{1,64}$", description="Catalogue slug, instead of ra/dec."
    ),
    size: SizeName = Query(config.DEFAULT_SIZE, description="small (3'), medium (6'), large (15')."),
    detector: int | None = Query(
        None, ge=1, le=6, description="SPHEREx detector 1-6. Default: the target's recommended one, else 3."
    ),
    wait_for: Literal["complete", "first_light", "preview"] = Query(
        "complete",
        description=(
            "For coordinate searches: 'first_light' answers 200 as soon as the 1st static "
            "image is rendered; 'preview' answers 200 once 1 frame per epoch is rendered; "
            "'complete' waits for full co-add."
        ),
    ),
    service: TimelineService = Depends(get_service),
):
    """Image timeline of a patch: one image per SPHEREx epoch.

    200 when ready. 202 while it is being built (call again after ``Retry-After`` seconds).
    502 when the build failed (it can be retried a minute later).
    """
    patch, detector = _resolve(service, ra, dec, target, detector)
    view = service.timeline(patch, detector, size)
    payload = timeline_payload(view, size, service.store)
    if view.status == "ready":
        return payload
    if view.status == "failed":
        return JSONResponse(status_code=502, content=payload)
    early_ready = (
        view.status == "building"
        and view.patch.target_slug is None
        and len(view.images) > 0
        and (
            config.PROGRESSIVE_EARLY_READY
            or wait_for == "first_light"
            or (wait_for == "preview" and view.timeline.stage in ("preview_ready", "refining"))
        )
    )
    if early_ready:
        return payload | {
            "status": "ready",
            "is_partial": True,
            "refining": True,
            "data": {"source": DATA_SOURCE, "processed_at": view.timeline.updated_at.isoformat()},
        }
    return JSONResponse(
        status_code=202, content=payload, headers={"Retry-After": str(RETRY_AFTER_S)}
    )


@app.get(f"{API_PREFIX}/timeline/diff")
def timeline_diff(
    a: int = Query(..., ge=0, description="Reference epoch index."),
    b: int = Query(..., ge=0, description="Epoch index compared against the reference."),
    ra: float | None = Query(None, ge=0.0, lt=360.0),
    dec: float | None = Query(None, ge=-90.0, le=90.0),
    target: str | None = Query(None, pattern=r"^[a-z0-9-]{1,64}$"),
    size: SizeName = Query(config.DEFAULT_SIZE),
    detector: int | None = Query(None, ge=1, le=6),
    service: TimelineService = Depends(get_service),
) -> Response:
    """PNG of epoch ``b`` minus epoch ``a``: red = brighter in b, blue = fainter, black = no change.

    Needs a ready timeline (it never starts a build). Header ``X-Diff-Limit`` is the brightness
    (MJy/sr) at full colour.
    """
    patch, detector = _resolve(service, ra, dec, target, detector)
    store = service.store
    timeline = store.get_timeline(patch.id, detector)
    if timeline is None or timeline.status != "ready":
        raise HTTPException(status_code=404, detail="Timeline not ready: request /timeline first.")
    by_epoch = {i.epoch_index: i for i in store.list_images(timeline.id, "large")}
    arrays = []
    for epoch in (a, b):
        npz = store.get_npz(by_epoch[epoch].id) if epoch in by_epoch else None
        if npz is None:
            raise HTTPException(status_code=404, detail=f"No float data for epoch {epoch}.")
        arrays.append(np.load(io.BytesIO(npz))["image"])
    side = imaging.grid_pixels(config.SIZES_DEG[size])
    png, limit = imaging.to_diff_png(*(imaging.crop_center(x, side) for x in arrays))
    return Response(content=png, media_type="image/png", headers={"X-Diff-Limit": f"{limit:.6g}"})


@app.get(f"{API_PREFIX}/images/{{image_id}}.png")
def get_image(image_id: int = Path(..., ge=1), store: Store = Depends(get_store)) -> Response:
    """A processed PNG. Ids change when a timeline is rebuilt, so it can be cached for long."""
    png = store.get_png(image_id)
    if png is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get(f"{API_PREFIX}/images/{{image_id}}.npz")
def get_image_npz(image_id: int = Path(..., ge=1), store: Store = Depends(get_store)) -> Response:
    """Raw float32 image and variance arrays for scientific analysis (large size only)."""
    npz = store.get_npz(image_id)
    if npz is None:
        raise HTTPException(status_code=404, detail="NPZ data not found.")
    return Response(
        content=npz,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/sectors")
def get_patch_sectors(
    patch_id: int = Path(..., ge=1),
    detector: int | None = Query(None, ge=1, le=6),
    store: Store = Depends(get_store),
) -> dict:
    """Stored sky-sector coordinates and per-exposure NASA IRSA sector footprints for a patch."""
    sectors = store.list_sector_coordinates(patch_id)
    if not sectors:
        raise HTTPException(status_code=404, detail="Patch sector coordinates not found.")
    exposures = store.list_nasa_sector_exposures(patch_id, detector=detector)
    return {
        "patch_id": patch_id,
        "sectors": sectors,
        "nasa_exposures": exposures,
    }


@app.get(f"{API_PREFIX}/catalogs/channels")
def list_channel_catalog(store: Store = Depends(get_store)) -> list[dict]:
    """Master table of the 102 SPHEREx spectral channels (Table 1.2, BLANKCH 51-52 marked)."""
    rows = store.list_spherex_channels()
    return rows or [asdict(ch) for ch in science_catalogs.SPHEREX_102_CHANNELS]


@app.get(f"{API_PREFIX}/catalogs/spectral-indices")
def list_spectral_index_catalog(store: Store = Depends(get_store)) -> list[dict]:
    """Master table of the 17 diagnostic spectral indices (Table 2.5)."""
    rows = store.list_spectral_indices()
    if rows:
        return rows
    return [asdict(idx) | {"feature_channels": list(idx.feature_channels)} for idx in science_catalogs.SPHEREX_17_INDICES]


# ----- science metrics, 17 spectral indices & ML Models 1, 2, 3 -------------------------


class EventClassifyRequest(BaseModel):
    patch_id: int | None = Field(default=None, ge=1)
    target: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    feature_vector: dict[str, float] | None = None
    temperature_t: float = Field(default=1.15, gt=0.05, le=10.0)


class SpectrumClassifyRequest(BaseModel):
    patch_id: int | None = Field(default=None, ge=1)
    target: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    scenario: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    spectrum: dict[str, Any] | None = None


class ForecastRequest(BaseModel):
    patch_id: int | None = Field(default=None, ge=1)
    target: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    scenario: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    times_mjd: list[float] | None = None
    fluxes_mjy: list[float] | None = None
    sigmas_mjy: list[float] | None = None
    horizon_days: float = Field(default=180.0, gt=1.0, le=730.0)
    period_days: float | None = Field(default=None, gt=0.01)


class AnalyzePatchRequest(BaseModel):
    scenario: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    force_recompute: bool = True


class CitizenVoteRequest(BaseModel):
    epoch_index: int = Field(default=-1, ge=-1)
    vote: Literal["REAL_CHANGE", "ARTIFACT", "MOVER", "UNSURE"]
    voter_token: str | None = Field(default=None, max_length=128)
    comment: str | None = Field(default=None, max_length=500)


def _patch_or_404(store: Store, patch_id: int) -> Patch:
    patch = store.get_patch(patch_id)
    if patch is None:
        raise HTTPException(status_code=404, detail=f"Patch {patch_id} not found.")
    return patch


def _resolve_optional_patch(
    service: TimelineService, patch_id: int | None, target: str | None
) -> Patch | None:
    if patch_id is not None:
        return _patch_or_404(service.store, patch_id)
    if target is not None:
        try:
            return service.resolve_patch(ra=None, dec=None, target_slug=target)
        except TargetNotFound:
            raise HTTPException(status_code=404, detail=f"Unknown target '{target}'.") from None
    return None


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/spectrum")
def get_patch_spectrum(
    patch_id: int = Path(..., ge=1),
    epoch_index: int = Query(-1, ge=-1),
    auto_compute: bool = Query(True),
    store: Store = Depends(get_store),
) -> dict:
    """102-channel SPHEREx spectrum (BLANKCH 51-52 preserved as null) and 17 spectral indices."""
    patch = _patch_or_404(store, patch_id)
    spec = store.get_patch_spectrum(patch_id, epoch_index=epoch_index)
    if spec is None and auto_compute:
        bundle = models.analyze_patch_science(store, patch, force_recompute=False)
        spec = bundle["spectrum"]
    if spec is None:
        raise HTTPException(status_code=404, detail="Patch spectrum not found.")
    return spec


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/metrics")
def get_patch_metrics(
    patch_id: int = Path(..., ge=1),
    detector: int | None = Query(None, ge=1, le=6),
    store: Store = Depends(get_store),
) -> dict:
    """Full scientific metrics bundle (photometry, variability, confidence, 17 spectral indices)."""
    patch = _patch_or_404(store, patch_id)
    bundle = models.analyze_patch_science(store, patch, force_recompute=False)
    image_photometry: list[dict[str, Any]] = []
    if detector is not None:
        tl = store.get_timeline(patch_id, detector)
        if tl is not None and tl.status == "ready":
            for img_info in store.list_images(tl.id, "large"):
                npz = store.get_npz(img_info.id)
                if npz is None:
                    continue
                data = np.load(io.BytesIO(npz))
                phot = metrics.extract_optimal_psf_photometry(data["image"], data["variance"])
                image_photometry.append({"epoch_index": img_info.epoch_index, "mid_mjd": img_info.mid_mjd, **phot})
    return {
        "patch": bundle["patch"],
        "confidence": bundle["confidence"],
        "variability": bundle["variability"],
        "spectral_indices": bundle["spectrum"].get("indices", []),
        "image_photometry": image_photometry,
    }


@app.post(f"{API_PREFIX}/patches/{{patch_id}}/analyze")
def analyze_patch(
    patch_id: int = Path(..., ge=1),
    body: AnalyzePatchRequest | None = None,
    store: Store = Depends(get_store),
) -> dict:
    """Run and persist the complete science pipeline (102 channels, 17 indices, Models 1, 2, 3)."""
    patch = _patch_or_404(store, patch_id)
    req = body or AnalyzePatchRequest()
    return models.analyze_patch_science(
        store,
        patch,
        scenario=req.scenario,
        force_recompute=req.force_recompute,
    )


@app.post(f"{API_PREFIX}/models/classify-event")
def classify_event(
    body: EventClassifyRequest,
    service: TimelineService = Depends(get_service),
) -> dict:
    """Model 1: Classify an astrophysical/instrumental event from 16 physical features."""
    store = service.store
    patch = _resolve_optional_patch(service, body.patch_id, body.target)
    if body.feature_vector is not None:
        fv = body.feature_vector
    elif patch is not None:
        profile_key = patch.target_slug or "barnards-star"
        if profile_key not in models.DEMO_PROFILE_SPECS:
            profile_key = "barnards-star"
        fv = models.DEMO_PROFILE_SPECS[profile_key]["features"]
    else:
        raise HTTPException(status_code=422, detail="Provide feature_vector, patch_id, or target.")

    result = models.run_model1_event_classifier(fv, temperature_t=body.temperature_t)
    if patch is not None:
        return store.save_model1_attribution(patch.id, -1, result)
    return result


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/models/event")
def get_patch_event_model(
    patch_id: int = Path(..., ge=1),
    store: Store = Depends(get_store),
) -> dict:
    """Retrieve stored Model 1 event attribution for a patch (computes if missing)."""
    patch = _patch_or_404(store, patch_id)
    row = store.get_model1_attribution(patch_id, epoch_index=-1)
    if row is None:
        row = models.analyze_patch_science(store, patch, force_recompute=False)["model1_event"]
    return row


@app.post(f"{API_PREFIX}/models/classify-spectrum")
def classify_spectrum(
    body: SpectrumClassifyRequest,
    service: TimelineService = Depends(get_service),
) -> dict:
    """Model 2: Fit 102-channel SPHEREx spectrum (BLANKCH 51-52 excluded) + Bayesian fusion."""
    store = service.store
    patch = _resolve_optional_patch(service, body.patch_id, body.target)
    if body.spectrum is not None:
        result = models.run_model2_spectral_classifier(body.spectrum)
        if patch is not None:
            return store.save_model2_classification(patch.id, result)
        return result

    if patch is not None:
        bundle = models.analyze_patch_science(
            store, patch, scenario=body.scenario, force_recompute=bool(body.scenario)
        )
        return bundle["model2_spectrum"]

    scenario = body.scenario or body.target
    if scenario and scenario in models.DEMO_PROFILE_SPECS:
        spec = models.build_demo_spectrum_payload(scenario)
        return models.run_model2_spectral_classifier(spec)
    raise HTTPException(status_code=422, detail="Provide spectrum, patch_id, target, or scenario.")


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/models/spectrum")
def get_patch_spectrum_model(
    patch_id: int = Path(..., ge=1),
    store: Store = Depends(get_store),
) -> dict:
    """Retrieve stored Model 2 spectral classification for a patch (computes if missing)."""
    patch = _patch_or_404(store, patch_id)
    row = store.get_model2_classification(patch_id)
    if row is None:
        row = models.analyze_patch_science(store, patch, force_recompute=False)["model2_spectrum"]
    return row


@app.post(f"{API_PREFIX}/models/forecast-temporal")
def forecast_temporal(
    body: ForecastRequest,
    service: TimelineService = Depends(get_service),
) -> dict:
    """Model 3: GP light-curve forecast, astrometric cone, and Model 1 alert handshake."""
    store = service.store
    patch = _resolve_optional_patch(service, body.patch_id, body.target)
    if body.times_mjd is not None and body.fluxes_mjy is not None:
        if len(body.times_mjd) != len(body.fluxes_mjy) or len(body.times_mjd) < 2:
            raise HTTPException(status_code=422, detail="times_mjd and fluxes_mjy must match and have length >= 2.")
        sigmas = body.sigmas_mjy or [
            science_catalogs.compute_reported_sigma(f, 0.015 * abs(f)) for f in body.fluxes_mjy
        ]
        m1_row = store.get_model1_attribution(patch.id, -1) if patch is not None else None
        ra = patch.ra if patch is not None else 0.0
        dec = patch.dec if patch is not None else 0.0
        result = models.run_model3_temporal_forecast(
            body.times_mjd,
            body.fluxes_mjy,
            sigmas,
            ra_deg=ra,
            dec_deg=dec,
            horizon_days=body.horizon_days,
            period_days=body.period_days,
            model1_result=m1_row,
            model1_attribution_id=m1_row["id"] if m1_row else None,
        )
        if patch is not None:
            return store.save_model3_forecast(patch.id, result)
        return result

    if patch is not None:
        bundle = models.analyze_patch_science(
            store, patch, scenario=body.scenario, force_recompute=bool(body.scenario)
        )
        return bundle["model3_forecast"]

    raise HTTPException(status_code=422, detail="Provide times_mjd + fluxes_mjy, patch_id, or target.")


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/models/forecast")
def get_patch_forecast_model(
    patch_id: int = Path(..., ge=1),
    store: Store = Depends(get_store),
) -> dict:
    """Retrieve stored Model 3 temporal forecast for a patch (computes if missing)."""
    patch = _patch_or_404(store, patch_id)
    row = store.get_model3_forecast(patch_id)
    if row is None:
        row = models.analyze_patch_science(store, patch, force_recompute=False)["model3_forecast"]
    return row


@app.post(f"{API_PREFIX}/patches/{{patch_id}}/votes")
def submit_citizen_vote(
    body: CitizenVoteRequest,
    patch_id: int = Path(..., ge=1),
    store: Store = Depends(get_store),
) -> dict:
    """Record a citizen-science classification vote on a patch."""
    _patch_or_404(store, patch_id)
    return store.save_citizen_vote(
        patch_id,
        body.epoch_index,
        body.vote,
        voter_token=body.voter_token,
        comment=body.comment,
    )


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/votes")
def list_citizen_votes(
    patch_id: int = Path(..., ge=1),
    epoch_index: int | None = Query(None, ge=-1),
    store: Store = Depends(get_store),
) -> list[dict]:
    """List citizen-science votes recorded for a patch."""
    _patch_or_404(store, patch_id)
    return store.list_citizen_votes(patch_id, epoch_index=epoch_index)
