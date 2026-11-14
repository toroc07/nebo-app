"""Nebo HTTP API. Run from the backend folder with: uvicorn app.main:app --reload"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from . import config, db, irsa
from .service import ServiceBusy, TargetNotFound, TimelineService, TimelineView
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
    allow_methods=["GET"],
    allow_headers=["*"],
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


def _patch_payload(patch: Patch) -> dict:
    return {"id": patch.id, "ra": patch.ra, "dec": patch.dec, "target": patch.target_slug}


def _detector_payload(detector: int) -> dict:
    return {
        "id": detector,
        "bandpass": irsa.bandpass_name(detector),
        "wavelength_range_um": list(irsa.DETECTOR_WAVELENGTH_RANGE_UM[detector]),
    }


def _timeline_payload(view: TimelineView, size: str) -> dict:
    base = {
        "status": view.status,
        "patch": _patch_payload(view.patch),
        "detector": _detector_payload(view.detector),
    }
    timeline = view.timeline
    if view.status == "building":
        return base | {
            "progress": {
                "stage": timeline.stage,
                "done": timeline.progress_done,
                "total": timeline.progress_total,
            },
            "retry_after_s": RETRY_AFTER_S,
        }
    if view.status == "failed":
        return base | {"error": timeline.error}

    side_px = view.images[0].width_px if view.images else None
    return base | {
        "size": {
            "name": size,
            "side_deg": config.SIZES_DEG[size],
            "side_arcmin": round(config.SIZES_DEG[size] * 60, 2),
            "width_px": side_px,
            "height_px": side_px,
            "pixel_scale_arcsec": config.PIXEL_SCALE_ARCSEC,
        },
        "orientation": "north_up_east_left",
        "display": {
            "stretch": "asinh",
            "unit": "MJy/sr",
            "note": "Zodiacal light subtracted; pixels without data are transparent.",
        },
        "epochs": [
            {
                "index": image.epoch_index,
                "start_utc": image.start_utc.isoformat(),
                "end_utc": image.end_utc.isoformat(),
                "mid_mjd": round(image.mid_mjd, 5),
                "frames_available": image.frames_available,
                "frames_used": image.frames_used,
                "display_min": image.display_min,
                "display_max": image.display_max,
                "image_url": f"{API_PREFIX}/images/{image.id}.png",
            }
            for image in view.images
        ],
        "frames_found": timeline.frames_found,
        "frames_used": timeline.frames_used,
        "updated_at": timeline.updated_at.isoformat(),
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
    service: TimelineService = Depends(get_service),
):
    """Image timeline of a patch: one image per SPHEREx epoch.

    200 when ready. 202 while it is being built (call again after ``Retry-After`` seconds).
    502 when the build failed (it can be retried a minute later).
    """
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

    view = service.timeline(patch, detector, size)
    payload = _timeline_payload(view, size)
    if view.status == "ready":
        return payload
    if view.status == "failed":
        return JSONResponse(status_code=502, content=payload)
    return JSONResponse(
        status_code=202, content=payload, headers={"Retry-After": str(RETRY_AFTER_S)}
    )


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
