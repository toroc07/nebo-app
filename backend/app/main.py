"""Nebo HTTP API. Run from the backend folder with: uvicorn app.main:app --reload"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import io
import math
from contextlib import asynccontextmanager
import logging
import os
import time
from typing import Any, Literal

import numpy as np

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import (
    chat,
    config,
    crossmatch,
    db,
    ephemeris,
    gaia,
    imaging,
    irsa,
    metrics,
    models,
    science_catalogs,
    wise,
)
from .service import (
    ARCHIVE_UNAVAILABLE,
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
# Early stages change quickly: poll faster so the first image shows as soon as it exists.
FAST_RETRY_AFTER_S = 2
FAST_STAGES = ("queued", "querying", "downloading", "first_light")


def retry_after_for(stage: str | None) -> int:
    return FAST_RETRY_AFTER_S if stage in FAST_STAGES else RETRY_AFTER_S
BUSY_RETRY_AFTER_S = 30
DEFAULT_DETECTOR = 3
SizeName = Literal["small", "medium", "large"]

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create the service (and open the DB pool) at startup so the first search is not slower."""
    try:
        get_service(get_store())
    except Exception as error:  # No DB yet: the endpoints answer 503 on their own.
        logging.getLogger(__name__).info("Warm-up skipped: %s", error)
    yield


app = FastAPI(
    lifespan=lifespan,
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
        return base | {
            "error": timeline.error,
            "code": "archive_unavailable" if timeline.error == ARCHIVE_UNAVAILABLE else "build_failed",
        }

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
            "retry_after_s": retry_after_for(timeline.stage),
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
    # Opt-in only (wait_for): the answer is a preview that keeps improving, and its image ids are
    # replaced by the next save, so the client must ask again after Retry-After.
    early_ready = (
        view.status == "building"
        and view.patch.target_slug is None
        and len(view.images) > 0
        and (
            wait_for == "first_light"
            or (
                wait_for == "preview"
                and view.timeline.stage in ("preview_ready", "refining", "rendering")
            )
        )
    )
    if early_ready:
        return JSONResponse(
            content=payload
            | {
                "status": "ready",
                "is_partial": True,
                "refining": True,
                "data": {
                    "source": DATA_SOURCE,
                    "processed_at": view.timeline.updated_at.isoformat(),
                },
            },
            headers={"Retry-After": str(retry_after_for(view.timeline.stage))},
        )
    return JSONResponse(
        status_code=202,
        content=payload,
        headers={"Retry-After": str(retry_after_for(view.timeline.stage))},
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


@app.get(f"{API_PREFIX}/timeline/rgb")
def timeline_rgb(
    r: int = Query(6, ge=1, le=6, description="Detector mapped to Red (long wavelength)."),
    g: int = Query(3, ge=1, le=6, description="Detector mapped to Green (medium wavelength)."),
    b: int = Query(1, ge=1, le=6, description="Detector mapped to Blue (short wavelength)."),
    epoch: int = Query(0, ge=0, description="Epoch index."),
    ra: float | None = Query(None, ge=0.0, lt=360.0),
    dec: float | None = Query(None, ge=-90.0, le=90.0),
    target: str | None = Query(None, pattern=r"^[a-z0-9-]{1,64}$"),
    size: SizeName = Query(config.DEFAULT_SIZE),
    service: TimelineService = Depends(get_service),
) -> Response:
    """False-color RGBA PNG combining three SPHEREx detectors (R=long, G=medium, B=short).

    Requires all three detector timelines to be ``ready`` with float32 ``.npz`` data; never
    starts a background build. Returns 404 with ``missing_detectors`` if any band is missing.
    """
    patch, _ = _resolve(service, ra, dec, target, None)
    store = service.store
    detectors = (r, g, b)
    missing: list[int] = []
    arrays: list[np.ndarray] = []
    for det in detectors:
        tl = store.get_timeline(patch.id, det)
        if tl is None or tl.status != "ready":
            missing.append(det)
            continue
        by_epoch = {img.epoch_index: img for img in store.list_images(tl.id, "large")}
        if epoch not in by_epoch:
            missing.append(det)
            continue
        npz = store.get_npz(by_epoch[epoch].id)
        if npz is None:
            missing.append(det)
            continue
        arrays.append(np.load(io.BytesIO(npz))["image"])
    if missing:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Missing ready detector timelines or float32 data for RGB composite.",
                "missing_detectors": sorted(set(missing)),
            },
        )
    side = imaging.grid_pixels(config.SIZES_DEG[size])
    png = imaging.to_rgb_png(*(imaging.crop_center(x, side) for x in arrays))
    return Response(content=png, media_type="image/png")


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


# ----- Gaia DR3 catalogue overlay ---------------------------------------------------------

# One query per patch covers the "large" image whatever its size, plus room for fast movers
# (Barnard's Star moves ~100" between J2016.0 and 2026).
GAIA_RADIUS_DEG = config.SIZES_DEG["large"] * math.sqrt(2) / 2 + 0.05
MAX_GAIA_EPOCHS = 50


def _patch_gaia_sources(store: Store, patch: Patch, g_max: float) -> list[gaia.GaiaSource]:
    """Gaia stars around a patch, from the api_query_cache table when they were asked before."""
    # The row limit is part of the key: an answer cut at another limit would misreport truncation.
    key = hashlib.sha256(
        f"gaia_dr3_cone:{patch.ra:.6f}:{patch.dec:.6f}:{GAIA_RADIUS_DEG:.5f}:{g_max:.2f}"
        f":{gaia.MAX_ROWS}".encode()
    ).hexdigest()
    cached = store.get_cached_api(key)
    if cached and isinstance(cached.get("response_json"), list):
        return [gaia.GaiaSource(**row) for row in cached["response_json"]]
    sources = gaia.query_cone(patch.ra, patch.dec, GAIA_RADIUS_DEG, g_max=g_max)
    store.set_cached_api(
        key,
        gaia.PROVIDER,
        [asdict(s) for s in sources],
        query_text=gaia.build_cone_query(patch.ra, patch.dec, GAIA_RADIUS_DEG, g_max),
        request_params={
            "patch_id": patch.id,
            "ra": patch.ra,
            "dec": patch.dec,
            "radius_deg": GAIA_RADIUS_DEG,
            "g_max": g_max,
        },
        row_count=len(sources),
    )
    return sources


def _round_or_none(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/gaia")
def get_patch_gaia(
    patch_id: int = Path(..., ge=1),
    size: SizeName = Query(config.DEFAULT_SIZE),
    mjd: list[float] = Query(
        ...,
        min_length=1,
        max_length=MAX_GAIA_EPOCHS,
        description="Dates (MJD) to place the stars at; pass each epoch's mid_mjd.",
    ),
    g_max: float = Query(gaia.DEFAULT_G_MAX, ge=6.0, le=21.0, description="Faintest Gaia G magnitude."),
    store: Store = Depends(get_store),
):
    """Catalogued Gaia DR3 stars on a patch image, moved to the date of each epoch.

    ``positions[i]`` matches ``mjd[i]``. Pixels use the same grid as the PNGs (north up, east
    left, row 0 at the top). A star is listed when it falls inside the image at any epoch.
    """
    patch = _patch_or_404(store, patch_id)
    try:
        sources = _patch_gaia_sources(store, patch, g_max)
    except gaia.GaiaQueryError as error:
        logging.getLogger(__name__).warning("Gaia query failed for patch %s: %s", patch_id, error)
        return JSONResponse(
            status_code=502,
            content={"code": "gaia_unavailable", "detail": "The Gaia archive did not answer. Retry later."},
            headers={"Retry-After": str(BUSY_RETRY_AFTER_S)},
        )

    wcs, (side, _) = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[size])
    stars = []
    for source in sources:
        positions = []
        for date in mjd:
            ra, dec = source.position_at(date)
            x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
            y = side - 1 - y  # FITS row 0 is the bottom; the PNG is flipped.
            positions.append(
                {
                    "mjd": date,
                    "ra": round(ra, 7),
                    "dec": round(dec, 7),
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "in_image": bool(-0.5 <= x <= side - 0.5 and -0.5 <= y <= side - 0.5),
                }
            )
        if not any(p["in_image"] for p in positions):
            continue
        pm_total = source.pm_total_mas_yr
        distance = source.distance_pc
        stars.append(
            {
                "source_id": source.source_id,
                "g_mag": _round_or_none(source.g_mag, 3),
                "bp_rp": _round_or_none(source.bp_rp, 3),
                "pm_ra_mas_yr": _round_or_none(source.pm_ra_mas_yr, 3),
                "pm_dec_mas_yr": _round_or_none(source.pm_dec_mas_yr, 3),
                "pm_total_mas_yr": _round_or_none(pm_total, 3),
                "parallax_mas": _round_or_none(source.parallax_mas, 4),
                "distance_pc": _round_or_none(distance, 2),
                "positions": positions,
            }
        )

    # The query keeps the brightest MAX_ROWS stars. When that limit is hit the list is only
    # complete down to the faintest star it returned, so "no Gaia star here" holds only that far.
    truncated = len(sources) >= gaia.MAX_ROWS
    g_complete = g_max
    if truncated:
        mags = [s.g_mag for s in sources if s.g_mag is not None]
        g_complete = round(max(mags), 3) if mags else g_max

    return {
        "patch_id": patch.id,
        "size": {"name": size, "width_px": side, "height_px": side},
        "catalog": {
            "name": gaia.CATALOG_NAME,
            "ref_epoch": gaia.REF_EPOCH_YEAR,
            "g_max": g_max,
            "g_complete": g_complete,
            "radius_deg": round(GAIA_RADIUS_DEG, 5),
            "truncated": truncated,
            "note": (
                "Positions propagated from J2016.0 with Gaia proper motions (parallax ignored). "
                "Cold brown dwarfs are too faint in visible light to appear in Gaia."
            ),
        },
        "mjd": mjd,
        "stars": stars,
    }


# ----- CatWISE2020 infrared overlay, cold candidates, alignment & suggested targets ------


def _patch_wise_sources(store: Store, patch: Patch, w2_max: float) -> list[wise.WiseSource]:
    """CatWISE2020 sources around a patch, cached in api_query_cache."""
    key = hashlib.sha256(
        f"catwise2020_cone:{patch.ra:.6f}:{patch.dec:.6f}:{GAIA_RADIUS_DEG:.5f}:{w2_max:.2f}"
        f":{wise.MAX_ROWS}".encode()
    ).hexdigest()
    cached = store.get_cached_api(key)
    if cached and isinstance(cached.get("response_json"), list):
        return [wise.WiseSource(**row) for row in cached["response_json"]]
    sources = wise.query_cone(patch.ra, patch.dec, GAIA_RADIUS_DEG, w2_max=w2_max)
    store.set_cached_api(
        key,
        wise.PROVIDER,
        [asdict(s) for s in sources],
        query_text=wise.build_cone_query(patch.ra, patch.dec, GAIA_RADIUS_DEG, w2_max),
        request_params={
            "patch_id": patch.id,
            "ra": patch.ra,
            "dec": patch.dec,
            "radius_deg": GAIA_RADIUS_DEG,
            "w2_max": w2_max,
        },
        row_count=len(sources),
    )
    return sources


def _gaia_completeness(sources: list[gaia.GaiaSource], g_max: float = gaia.DEFAULT_G_MAX) -> tuple[float, bool]:
    truncated = len(sources) >= gaia.MAX_ROWS
    if not truncated:
        return g_max, False
    mags = [s.g_mag for s in sources if s.g_mag is not None]
    return (round(max(mags), 3) if mags else g_max), True


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/wise")
def get_patch_wise(
    patch_id: int = Path(..., ge=1),
    size: SizeName = Query(config.DEFAULT_SIZE),
    mjd: list[float] = Query(
        ...,
        min_length=1,
        max_length=MAX_GAIA_EPOCHS,
        description="Dates (MJD) to place the sources at; pass each epoch's mid_mjd.",
    ),
    w2_max: float = Query(wise.DEFAULT_W2_MAX, ge=6.0, le=20.0, description="Faintest WISE W2 magnitude."),
    crossmatch_gaia: bool = Query(True, description="Cross-match against Gaia DR3 to flag cold candidates."),
    cold_w1_w2_min: float = Query(1.0, ge=0.0, le=6.0, description="Minimum W1-W2 colour for cold candidates."),
    gaia_match_radius_arcsec: float = Query(3.0, gt=0.1, le=30.0),
    store: Store = Depends(get_store),
):
    """Catalogued CatWISE2020 infrared sources on a patch, with optional Gaia DR3 cross-match."""
    patch = _patch_or_404(store, patch_id)
    try:
        wise_sources = _patch_wise_sources(store, patch, w2_max)
    except wise.WiseQueryError as error:
        logging.getLogger(__name__).warning("CatWISE2020 query failed for patch %s: %s", patch_id, error)
        return JSONResponse(
            status_code=502,
            content={"code": "wise_unavailable", "detail": "The IRSA CatWISE2020 service did not answer. Retry later."},
            headers={"Retry-After": str(BUSY_RETRY_AFTER_S)},
        )

    gaia_sources: list[gaia.GaiaSource] = []
    gaia_available = False
    g_complete: float | None = None
    if crossmatch_gaia:
        try:
            gaia_sources = _patch_gaia_sources(store, patch, gaia.DEFAULT_G_MAX)
            gaia_available = True
            g_complete, _ = _gaia_completeness(gaia_sources, gaia.DEFAULT_G_MAX)
        except gaia.GaiaQueryError:
            gaia_available = False

    wcs, (side, _) = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[size])
    ref_mjd = mjd[-1]
    sources_out = []
    for source in wise_sources:
        positions = []
        for date in mjd:
            ra, dec = source.position_at(date)
            x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
            y = side - 1 - y
            positions.append(
                {
                    "mjd": date,
                    "ra": round(ra, 7),
                    "dec": round(dec, 7),
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "in_image": bool(-0.5 <= x <= side - 0.5 and -0.5 <= y <= side - 0.5),
                }
            )
        if not any(p["in_image"] for p in positions):
            continue

        gaia_match = None
        if gaia_available and gaia_sources:
            sra, sdec = source.position_at(ref_mjd)
            best_g = gaia.nearest(gaia_sources, sra, sdec, ref_mjd)
            if best_g is not None and best_g[1] <= gaia_match_radius_arcsec:
                gsrc, gdist = best_g
                gaia_match = {
                    "source_id": gsrc.source_id,
                    "dist_arcsec": round(gdist, 3),
                    "g_mag": _round_or_none(gsrc.g_mag, 3),
                }

        w1_w2 = source.w1_w2_color
        cold_candidate = bool(
            gaia_available
            and gaia_match is None
            and w1_w2 is not None
            and w1_w2 >= cold_w1_w2_min
        )
        sources_out.append(
            {
                "source_id": source.source_id,
                "w1_mag": _round_or_none(source.w1_mag, 3),
                "w2_mag": _round_or_none(source.w2_mag, 3),
                "w1_w2_color": _round_or_none(w1_w2, 3),
                "pm_ra_mas_yr": _round_or_none(source.pm_ra_mas_yr, 3),
                "pm_dec_mas_yr": _round_or_none(source.pm_dec_mas_yr, 3),
                "pm_total_mas_yr": _round_or_none(source.pm_total_mas_yr, 3),
                "gaia_match": gaia_match,
                "cold_candidate": cold_candidate,
                "positions": positions,
            }
        )

    truncated = len(wise_sources) >= wise.MAX_ROWS
    w2_complete = w2_max
    if truncated:
        mags = [s.w2_mag for s in wise_sources if s.w2_mag is not None]
        w2_complete = round(max(mags), 3) if mags else w2_max

    return {
        "patch_id": patch.id,
        "size": {"name": size, "width_px": side, "height_px": side},
        "catalog": {
            "name": wise.CATALOG_NAME,
            "ref_epoch": wise.REF_EPOCH_YEAR,
            "w2_max": w2_max,
            "w2_complete": w2_complete,
            "radius_deg": round(GAIA_RADIUS_DEG, 5),
            "truncated": truncated,
            "gaia_crossmatched": gaia_available,
            "gaia_complete_to_g": g_complete,
        },
        "mjd": mjd,
        "sources": sources_out,
    }


def _load_epoch_arrays(
    store: Store, patch_id: int, detector: int, size: SizeName
) -> tuple[list[Any], dict[int, np.ndarray]]:
    tl = store.get_timeline(patch_id, detector)
    if tl is None or tl.status != "ready":
        raise HTTPException(status_code=404, detail="Timeline not ready for this patch and detector.")
    images = store.list_images(tl.id, size)
    if not images:
        raise HTTPException(status_code=404, detail="No images found for this size.")
    # Only the largest size stores float32 arrays; smaller sizes are its centre crop (as their PNGs).
    largest = max(config.SIZES_DEG, key=config.SIZES_DEG.get)
    side = imaging.grid_pixels(config.SIZES_DEG[size])
    arrays: dict[int, np.ndarray] = {}
    for img in store.list_images(tl.id, largest):
        npz = store.get_npz(img.id)
        if npz is not None:
            arrays[img.epoch_index] = imaging.crop_center(np.load(io.BytesIO(npz))["image"], side)
    return images, arrays


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/candidates")
def get_patch_candidates(
    patch_id: int = Path(..., ge=1),
    detector: int = Query(3, ge=1, le=6),
    size: SizeName = Query(config.DEFAULT_SIZE),
    epoch_a: int = Query(0, ge=0),
    epoch_b: int | None = Query(None, ge=0),
    snr_threshold: float = Query(4.0, ge=2.0, le=20.0),
    store: Store = Depends(get_store),
):
    """Detect epoch-to-epoch changes and label each as catalogued_object or candidate_signal."""
    patch = _patch_or_404(store, patch_id)
    images, arrays = _load_epoch_arrays(store, patch_id, detector, size)
    by_epoch = {img.epoch_index: img for img in images}
    if epoch_b is None:
        epoch_b = max(by_epoch.keys())
    if epoch_a not in arrays or epoch_b not in arrays:
        raise HTTPException(status_code=404, detail="Float32 arrays (.npz) missing for requested epochs.")

    wcs, _ = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[size])
    detections = crossmatch.detect_epoch_changes(
        arrays[epoch_a], arrays[epoch_b], wcs, snr_threshold=snr_threshold
    )

    gaia_sources: list[gaia.GaiaSource] = []
    gaia_available = False
    g_complete: float | None = None
    try:
        gaia_sources = _patch_gaia_sources(store, patch, gaia.DEFAULT_G_MAX)
        gaia_available = True
        g_complete, _ = _gaia_completeness(gaia_sources, gaia.DEFAULT_G_MAX)
    except gaia.GaiaQueryError:
        gaia_available = False

    wise_sources: list[wise.WiseSource] = []
    wise_available = False
    try:
        wise_sources = _patch_wise_sources(store, patch, wise.DEFAULT_W2_MAX)
        wise_available = True
    except wise.WiseQueryError:
        wise_available = False

    candidates = crossmatch.classify_changes(
        detections,
        gaia_sources,
        wise_sources,
        mjd_a=by_epoch[epoch_a].mid_mjd,
        mjd_b=by_epoch[epoch_b].mid_mjd,
        g_complete=g_complete,
    )
    return {
        "patch_id": patch.id,
        "detector": detector,
        "size": size,
        "epoch_a": epoch_a,
        "epoch_b": epoch_b,
        "gaia_available": gaia_available,
        "wise_available": wise_available,
        "gaia_complete_to_g": g_complete,
        "candidates": candidates,
        # Detection stops at the cap: there may be more changes than listed.
        "truncated": len(detections) >= crossmatch.MAX_CANDIDATES,
    }


@app.get(f"{API_PREFIX}/patches/{{patch_id}}/alignment")
def get_patch_alignment(
    patch_id: int = Path(..., ge=1),
    detector: int = Query(3, ge=1, le=6),
    size: SizeName = Query(config.DEFAULT_SIZE),
    store: Store = Depends(get_store),
):
    """Check astrometric alignment per epoch against slow Gaia DR3 reference stars."""
    patch = _patch_or_404(store, patch_id)
    images, arrays = _load_epoch_arrays(store, patch_id, detector, size)
    try:
        gaia_sources = _patch_gaia_sources(store, patch, gaia.DEFAULT_G_MAX)
    except gaia.GaiaQueryError:
        return JSONResponse(
            status_code=502,
            content={"code": "gaia_unavailable", "detail": "The Gaia archive did not answer. Retry later."},
            headers={"Retry-After": str(BUSY_RETRY_AFTER_S)},
        )

    wcs, _ = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[size])
    epochs_out = []
    for img in images:
        arr = arrays.get(img.epoch_index)
        if arr is None:
            continue
        metrics_row = crossmatch.check_epoch_alignment(arr, wcs, gaia_sources, img.mid_mjd)
        epochs_out.append({"epoch_index": img.epoch_index, "mid_mjd": img.mid_mjd} | metrics_row)
    return {
        "patch_id": patch.id,
        "detector": detector,
        "size": size,
        "epochs": epochs_out,
    }


_CURATED_SUGGESTED_DESTINATIONS: tuple[dict[str, Any], ...] = (
    {
        "source_id": "4472832130114786688",
        "name": "Barnard's Star",
        "ra": 269.446223,
        "dec": 4.768780,
        "pm_total_mas_yr": 10393.4,
        "distance_pc": 1.83,
        "g_mag": 8.19,
        "bp_rp": 2.83,
    },
    {
        "source_id": "5853498713190525696",
        "name": "Proxima Centauri",
        "ra": 217.392321,
        "dec": -62.676075,
        "pm_total_mas_yr": 3853.0,
        "distance_pc": 1.30,
        "g_mag": 8.98,
        "bp_rp": 3.80,
    },
    {
        "source_id": "4810594479418041856",
        "name": "Kapteyn's Star",
        "ra": 77.934792,
        "dec": -45.026583,
        "pm_total_mas_yr": 8670.5,
        "distance_pc": 3.93,
        "g_mag": 8.05,
        "bp_rp": 2.13,
    },
    {
        "source_id": "4075141768785646848",
        "name": "Ross 154",
        "ra": 282.456750,
        "dec": -23.836222,
        "pm_total_mas_yr": 665.2,
        "distance_pc": 2.98,
        "g_mag": 9.13,
        "bp_rp": 2.94,
    },
)


@app.get(f"{API_PREFIX}/explore/suggested")
def get_suggested_destinations(
    ra: float | None = Query(None, ge=0.0, lt=360.0),
    dec: float | None = Query(None, ge=-90.0, le=90.0),
    radius_deg: float = Query(30.0, gt=0.1, le=90.0),
    limit: int = Query(12, ge=1, le=50),
    store: Store = Depends(get_store),
):
    """Nearby or high-proper-motion Gaia DR3 stars to suggest in the sky explorer."""
    ref_mjd = ephemeris.REFERENCE_MJD
    cache_key = hashlib.sha256(
        f"gaia_suggested:{ra}:{dec}:{radius_deg:.2f}:{limit}".encode()
    ).hexdigest()
    cached = store.get_cached_api(cache_key)
    if cached and isinstance(cached.get("response_json"), list):
        sources = [gaia.GaiaSource(**row) for row in cached["response_json"]]
        source_kind = gaia.PROVIDER
    else:
        try:
            sources = gaia.query_suggested_destinations(
                ra=ra, dec=dec, radius_deg=radius_deg, limit=limit
            )
            store.set_cached_api(
                cache_key,
                "gaia_suggested_tap",
                [asdict(s) for s in sources],
                query_text=gaia.build_suggested_query(
                    ra=ra, dec=dec, radius_deg=radius_deg, limit=limit
                ),
                request_params={"ra": ra, "dec": dec, "radius_deg": radius_deg, "limit": limit},
                row_count=len(sources),
            )
            source_kind = gaia.PROVIDER
        except gaia.GaiaQueryError:
            return {
                "source": "curated_fallback",
                "destinations": list(_CURATED_SUGGESTED_DESTINATIONS[:limit]),
            }

    destinations = []
    for s in sources:
        prop_ra, prop_dec = s.position_at(ref_mjd)
        destinations.append(
            {
                "source_id": s.source_id,
                "name": f"Gaia DR3 {s.source_id}",
                "ra": round(prop_ra, 6),
                "dec": round(prop_dec, 6),
                "pm_total_mas_yr": _round_or_none(s.pm_total_mas_yr, 2),
                "distance_pc": _round_or_none(s.distance_pc, 2),
                "g_mag": _round_or_none(s.g_mag, 3),
                "bp_rp": _round_or_none(s.bp_rp, 3),
            }
        )
    return {"source": source_kind, "destinations": destinations}


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


# The GP forecast costs O(n^3) in the number of points; a light curve longer than this is refused.
MAX_FORECAST_POINTS = 500
SPECTRUM_CHANNELS = 102
SPECTRUM_LIST_KEYS = ("flux_mjy", "sigma_reported_mjy", "valid_mask")


class ForecastRequest(BaseModel):
    patch_id: int | None = Field(default=None, ge=1)
    target: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    scenario: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    times_mjd: list[float] | None = Field(default=None, max_length=MAX_FORECAST_POINTS)
    fluxes_mjy: list[float] | None = Field(default=None, max_length=MAX_FORECAST_POINTS)
    sigmas_mjy: list[float] | None = Field(default=None, max_length=MAX_FORECAST_POINTS)
    horizon_days: float = Field(default=180.0, gt=1.0, le=730.0)
    period_days: float | None = Field(default=None, gt=0.01)


class AnalyzePatchRequest(BaseModel):
    scenario: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,64}$")
    force_recompute: bool = False


def _simulated(row: dict) -> dict:
    """Label a result derived from the built-in demonstration profiles, never from real data."""
    return row | {"simulated": True, "data_note": models.SIMULATED_NOTE}


def _from_user_input(row: dict) -> dict:
    """A result computed from data the caller sent. It is returned, never stored on a patch:
    anyone can call these endpoints, and a stored row would replace the patch's own result."""
    return row | {"simulated": False, "data_note": "Computed from the data sent in the request."}


# Recomputing a patch's science bundle is heavy and the API is public: one forced run per patch
# in this window, per process.
ANALYZE_COOLDOWN_S = 60.0
_last_forced_analysis: dict[int, float] = {}


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


def spectrum_channels(spec: dict) -> list[dict]:
    """One entry per SPHEREx channel, as the web client draws them.

    The stored spectrum is columnar (index i = channel i + 1); the catalog adds channel id,
    band and central wavelength. BLANKCH and invalid channels get a null flux, never 0.
    """
    flux = spec.get("flux_mjy") or []
    sigma = spec.get("sigma_reported_mjy") or []
    valid = spec.get("valid_mask") or []
    out = []
    for i, ch in enumerate(science_catalogs.SPHEREX_102_CHANNELS):
        ok = i < len(flux) and flux[i] is not None and (valid[i] if i < len(valid) else True)
        out.append({
            "channel_id": ch.channel_id,
            "band": ch.band,
            "lambda_c_um": ch.lambda_c_um,
            "flux_mjy": flux[i] if ok and not ch.is_blankch else None,
            "sigma_mjy": sigma[i] if ok and not ch.is_blankch and i < len(sigma) else None,
            "is_blankch": ch.is_blankch,
        })
    return out


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
    return _simulated(spec | {"channels": spectrum_channels(spec)})


def _epoch_saturation(exposures: list[dict[str, Any]], image: Any) -> dict[str, Any]:
    """Frames of this epoch with OVERFLOW/SUR_ERROR in the photometry box around the object."""
    # The epoch spans the mjd_start of its frames (render_epoch_images); 1 s of slack for rounding.
    lo = datetime_to_mjd(image.start_utc) - 1e-5
    hi = datetime_to_mjd(image.end_utc) + 1e-5
    flags = [e.get("saturated_near_target") for e in exposures if lo <= e["mjd_start"] <= hi]
    known = [f for f in flags if f is not None]
    saturated = sum(known)
    return {
        # Tri-state: unchecked frames (e.g. the cutout could not be fetched) never count as clean.
        "saturated": True if saturated else (False if flags and len(known) == len(flags) else None),
        "saturated_frames": saturated,
        "checked_frames": len(known),
        "total_frames": len(flags),
        "saturated_frac": round(saturated / len(known), 3) if known else None,
    }


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
            target = store.get_target(patch.target_slug) if patch.target_slug else None
            exposures = store.list_nasa_sector_exposures(patch_id, detector)
            for img_info in store.list_images(tl.id, "large"):
                npz = store.get_npz(img_info.id)
                if npz is None:
                    continue
                data = np.load(io.BytesIO(npz))
                # Moving targets (Barnard: ~1.7 px/yr) are measured where they are at this epoch.
                center = None
                expected = _expected_position(patch, target, img_info.mid_mjd, "large")
                if expected is not None and expected["in_image"]:
                    side = data["image"].shape[0]
                    center = (expected["x"], side - 1 - expected["y"])  # npz rows are unflipped FITS
                phot = metrics.extract_optimal_psf_photometry(
                    data["image"], data["variance"], center_xy=center
                )
                saturation = _epoch_saturation(exposures, img_info)
                if saturation["saturated"]:
                    # Saturated cores are NaN or clipped: the flux is only an approximate lower
                    # limit and the propagated sigma ignores the missing core.
                    phot |= {"sigma_stat": None, "sigma_reported": None, "snr": None}
                image_photometry.append(
                    {"epoch_index": img_info.epoch_index, "mid_mjd": img_info.mid_mjd, **phot, **saturation}
                )
    return {
        "patch": bundle["patch"],
        # Confidence, variability and indices are simulated; image_photometry is measured on
        # this patch's SPHEREx images.
        "simulated": True,
        "data_note": models.SIMULATED_NOTE
        + " image_photometry is measured on this patch's SPHEREx images.",
        "confidence": bundle["confidence"],
        "variability": bundle["variability"],
        "spectral_indices": bundle["spectrum"].get("indices", []),
        "image_photometry": image_photometry,
    }


def _resolve_patch_crossmatch(
    store: Store, patch: Patch
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Best-effort Gaia DR3 and CatWISE2020 cross-match for Model 1 enrichment."""
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    g_sources: list[gaia.GaiaSource] = []
    w_sources: list[wise.WiseSource] = []

    g_key = hashlib.sha256(
        f"gaia_dr3_cone:{patch.ra:.6f}:{patch.dec:.6f}:{GAIA_RADIUS_DEG:.5f}:{gaia.DEFAULT_G_MAX:.2f}"
        f":{gaia.MAX_ROWS}".encode()
    ).hexdigest()
    if store.get_cached_api(g_key) or not in_pytest or gaia.query_cone.__module__ != "app.gaia":
        try:
            g_sources = _patch_gaia_sources(store, patch, gaia.DEFAULT_G_MAX)
        except gaia.GaiaQueryError:
            g_sources = []

    w_key = hashlib.sha256(
        f"catwise2020_cone:{patch.ra:.6f}:{patch.dec:.6f}:{GAIA_RADIUS_DEG:.5f}:{wise.DEFAULT_W2_MAX:.2f}"
        f":{wise.MAX_ROWS}".encode()
    ).hexdigest()
    if store.get_cached_api(w_key) or not in_pytest or wise.query_cone.__module__ != "app.wise":
        try:
            w_sources = _patch_wise_sources(store, patch, wise.DEFAULT_W2_MAX)
        except wise.WiseQueryError:
            w_sources = []

    if not g_sources and not w_sources:
        return None, None
    return crossmatch.patch_crossmatch_summary(
        patch.ra, patch.dec, ephemeris.REFERENCE_MJD, g_sources, w_sources
    )


@app.post(f"{API_PREFIX}/patches/{{patch_id}}/analyze")
def analyze_patch(
    patch_id: int = Path(..., ge=1),
    body: AnalyzePatchRequest | None = None,
    store: Store = Depends(get_store),
) -> dict:
    """Run and persist the complete science pipeline (102 channels, 17 indices, Models 1, 2, 3)."""
    patch = _patch_or_404(store, patch_id)
    req = body or AnalyzePatchRequest()
    if req.force_recompute or req.scenario:
        now = time.monotonic()
        last = _last_forced_analysis.get(patch_id)
        if last is not None and now - last < ANALYZE_COOLDOWN_S:
            wait = int(ANALYZE_COOLDOWN_S - (now - last)) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Patch analysed recently; retry in {wait} s.",
                headers={"Retry-After": str(wait)},
            )
        _last_forced_analysis[patch_id] = now
    gaia_info, wise_info = (None, None) if req.scenario else _resolve_patch_crossmatch(store, patch)
    return models.analyze_patch_science(
        store,
        patch,
        scenario=req.scenario,
        force_recompute=req.force_recompute,
        gaia_info=gaia_info,
        wise_info=wise_info,
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
        gaia_info, wise_info = _resolve_patch_crossmatch(store, patch)
        fv = models.enrich_features_from_catalogs(
            models.DEMO_PROFILE_SPECS[profile_key]["features"], gaia_info, wise_info
        )
        if gaia_info is not None or wise_info is not None:
            store.save_patch_crossmatch(patch.id, gaia_info, wise_info)
    else:
        raise HTTPException(status_code=422, detail="Provide feature_vector, patch_id, or target.")

    result = models.run_model1_event_classifier(fv, temperature_t=body.temperature_t)
    if body.feature_vector is not None:
        return _from_user_input(result)
    assert patch is not None
    return _simulated(store.save_model1_attribution(patch.id, -1, result))


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
    return _simulated(row)


@app.post(f"{API_PREFIX}/models/classify-spectrum")
def classify_spectrum(
    body: SpectrumClassifyRequest,
    service: TimelineService = Depends(get_service),
) -> dict:
    """Model 2: Fit 102-channel SPHEREx spectrum (BLANKCH 51-52 excluded) + Bayesian fusion."""
    store = service.store
    patch = _resolve_optional_patch(service, body.patch_id, body.target)
    if body.spectrum is not None:
        for key in SPECTRUM_LIST_KEYS:
            values = body.spectrum.get(key)
            if values is not None and (
                not isinstance(values, list) or len(values) != SPECTRUM_CHANNELS
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"spectrum.{key} must be a list of {SPECTRUM_CHANNELS} values.",
                )
        try:
            result = models.run_model2_spectral_classifier(body.spectrum)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"Invalid spectrum: {error}") from None
        return _from_user_input(result)

    if patch is not None:
        bundle = models.analyze_patch_science(
            store, patch, scenario=body.scenario, force_recompute=bool(body.scenario)
        )
        return _simulated(bundle["model2_spectrum"])

    scenario = body.scenario or body.target
    if scenario and scenario in models.DEMO_PROFILE_SPECS:
        spec = models.build_demo_spectrum_payload(scenario)
        return _simulated(models.run_model2_spectral_classifier(spec))
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
    return _simulated(row)


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
        if body.sigmas_mjy is not None and len(body.sigmas_mjy) != len(body.fluxes_mjy):
            raise HTTPException(status_code=422, detail="sigmas_mjy must have the same length as fluxes_mjy.")
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
        return _from_user_input(result)

    if patch is not None:
        bundle = models.analyze_patch_science(
            store, patch, scenario=body.scenario, force_recompute=bool(body.scenario)
        )
        return _simulated(bundle["model3_forecast"])

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
    return _simulated(row)


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
    """List citizen-science votes recorded for a patch (voter tokens are never listed)."""
    _patch_or_404(store, patch_id)
    return [
        {key: value for key, value in vote.items() if key != "voter_token"}
        for vote in store.list_citizen_votes(patch_id, epoch_index=epoch_index)
    ]


# ----- public chat ------------------------------------------------------------------------

_chat_flood = chat.FloodGuard()
_CHAT_MAX_AGE_S = chat.RETENTION_HOURS * 3600.0


class ChatMessageRequest(BaseModel):
    nickname: str = Field(..., max_length=32)
    # Generous here so an over-long message gets the friendly "too_long" answer below.
    body: str = Field(..., max_length=2000)


def _chat_room_or_404(store: Store, room: str) -> str:
    """'general' or the slug of a catalogue object."""
    if room != chat.GENERAL_ROOM and (not chat.valid_room(room) or store.get_target(room) is None):
        raise HTTPException(status_code=404, detail="Unknown chat room.")
    return room


def _chat_message_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "body": row["body"],
        "created_at": row["created_at"].isoformat(),
    }


def _client_address(request: Request) -> str:
    """The caller's address for the anti-flood limit, never stored. Cloud Run's proxy appends the
    real address to X-Forwarded-For, so the last entry is used (the first one can be forged)."""
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    forwarded = [part for part in forwarded if part]
    if forwarded:
        return forwarded[-1]
    return request.client.host if request.client else "unknown"


@app.get(f"{API_PREFIX}/chat/{{room}}/messages")
def list_chat_messages(
    room: str = Path(..., pattern=r"^[a-z0-9-]{1,64}$"),
    after: int = Query(0, ge=0, description="Only messages with a larger id (for polling)."),
    store: Store = Depends(get_store),
) -> dict:
    """Public chat of a catalogue object ('general' for everyone else), oldest first.

    Without ``after``: the latest messages. Poll with ``after`` = the last id received.
    Messages are deleted after 24 hours.
    """
    _chat_room_or_404(store, room)
    rows = store.list_chat_messages(room, after, chat.PAGE_SIZE, _CHAT_MAX_AGE_S)
    return {
        "room": room,
        "retention_hours": chat.RETENTION_HOURS,
        "max_length": chat.MAX_LENGTH,
        "messages": [_chat_message_payload(row) for row in rows],
    }


@app.post(f"{API_PREFIX}/chat/{{room}}/messages", status_code=201)
def post_chat_message(
    body: ChatMessageRequest,
    request: Request,
    room: str = Path(..., pattern=r"^[a-z0-9-]{1,64}$"),
    store: Store = Depends(get_store),
):
    """Post to a public chat room. Filtered on the server: no banned words, links, email
    addresses, handles or phone numbers. 422 with ``code`` when refused, 429 when too fast."""
    _chat_room_or_404(store, room)
    try:
        nickname = chat.check_nickname(body.nickname)
        text = chat.check_message(body.body)
    except chat.ChatRejected as error:
        return JSONResponse(status_code=422, content={"code": error.code, "detail": str(error)})
    wait = _chat_flood.wait_s(_client_address(request))
    if wait > 0:
        seconds = int(wait) + 1
        return JSONResponse(
            status_code=429,
            content={"code": "too_fast", "detail": f"Wait {seconds} s before sending another message."},
            headers={"Retry-After": str(seconds)},
        )
    store.purge_chat_messages(_CHAT_MAX_AGE_S)
    return _chat_message_payload(store.add_chat_message(room, nickname, text))
