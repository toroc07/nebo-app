"""Cross-matching, epoch-change attribution, and Gaia astrometric alignment checks.

Pure NumPy + Astropy WCS routines that operate on the float32 epoch arrays produced by
``imaging.to_npz`` and the catalog sources from ``gaia.py`` and ``wise.py``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import config, gaia, wise


def _robust_sigma(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0
    med = float(np.median(finite))
    mad = float(np.median(np.abs(finite - med)))
    return max(1.4826 * mad, 1e-6)


MAX_CANDIDATES = 25


def detect_epoch_changes(
    image_a: np.ndarray,
    image_b: np.ndarray,
    wcs: Any,
    *,
    snr_threshold: float = 4.0,
    min_separation_px: int = 3,
    max_candidates: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Find significant point-like changes in ``image_b - image_a`` (FITS orientation)."""
    if image_a.shape != image_b.shape:
        return []
    diff = image_b.astype(np.float64) - image_a.astype(np.float64)
    finite = np.isfinite(diff)
    if not finite.any():
        return []

    med = float(np.median(diff[finite]))
    centered = diff - med
    sigma = _robust_sigma(centered)
    abs_snr = np.where(finite, np.abs(centered) / sigma, 0.0)

    ny, nx = diff.shape
    raw_peaks: list[tuple[float, int, int]] = []
    for y in range(1, ny - 1):
        for x in range(1, nx - 1):
            val = float(abs_snr[y, x])
            if val < snr_threshold:
                continue
            patch = abs_snr[y - 1 : y + 2, x - 1 : x + 2]
            if val >= float(np.max(patch)):
                raw_peaks.append((val, x, y))

    raw_peaks.sort(reverse=True)
    kept: list[tuple[float, int, int]] = []
    for snr, x, y in raw_peaks:
        if any(math.hypot(x - kx, y - ky) < min_separation_px for _, kx, ky in kept):
            continue
        kept.append((snr, x, y))
        if len(kept) >= max_candidates:
            break

    detections: list[dict[str, Any]] = []
    for snr, x_fits, y_fits in kept:
        ra, dec = (float(v) for v in wcs.pixel_to_world_values(x_fits, y_fits))
        y_png = ny - 1 - y_fits
        delta = float(centered[y_fits, x_fits])
        detections.append(
            {
                "ra": round(ra % 360.0, 7),
                "dec": round(dec, 7),
                "x": int(x_fits),
                "y": int(y_png),
                "snr": round(snr, 2),
                "delta_flux": round(delta, 5),
                "polarity": "positive" if delta >= 0 else "negative",
            }
        )
    return detections


def classify_changes(
    detections: list[dict[str, Any]],
    gaia_sources: list[gaia.GaiaSource],
    wise_sources: list[wise.WiseSource],
    *,
    mjd_a: float,
    mjd_b: float,
    g_complete: float | None,
    match_radius_arcsec: float = config.PIXEL_SCALE_ARCSEC,
) -> list[dict[str, Any]]:
    """Label each detected change as ``catalogued_object`` or ``candidate_signal``."""
    out: list[dict[str, Any]] = []
    for det in detections:
        ra, dec = det["ra"], det["dec"]
        gaia_match = None
        if gaia_sources:
            m_a = gaia.nearest(gaia_sources, ra, dec, mjd_a)
            m_b = gaia.nearest(gaia_sources, ra, dec, mjd_b)
            best_g = min(
                (m for m in (m_a, m_b) if m is not None),
                key=lambda m: m[1],
                default=None,
            )
            if best_g is not None and best_g[1] <= match_radius_arcsec:
                src, dist = best_g
                gaia_match = {
                    "source_id": src.source_id,
                    "dist_arcsec": round(dist, 3),
                    "g_mag": None if src.g_mag is None else round(src.g_mag, 3),
                    "pm_total_mas_yr": (
                        None if src.pm_total_mas_yr is None else round(src.pm_total_mas_yr, 2)
                    ),
                }

        wise_match = None
        if wise_sources:
            best_w = wise.nearest(wise_sources, ra, dec, mjd_b)
            if best_w is not None and best_w[1] <= match_radius_arcsec:
                wsrc, wdist = best_w
                wise_match = {
                    "source_id": wsrc.source_id,
                    "dist_arcsec": round(wdist, 3),
                    "w1_mag": None if wsrc.w1_mag is None else round(wsrc.w1_mag, 3),
                    "w2_mag": None if wsrc.w2_mag is None else round(wsrc.w2_mag, 3),
                    "w1_w2_color": (
                        None if wsrc.w1_w2_color is None else round(wsrc.w1_w2_color, 3)
                    ),
                }

        is_known = gaia_match is not None or wise_match is not None
        out.append(
            det
            | {
                "classification": "catalogued_object" if is_known else "candidate_signal",
                "gaia_match": gaia_match,
                "wise_match": wise_match,
                "gaia_complete_to_g": g_complete,
            }
        )
    return out


def check_epoch_alignment(
    image: np.ndarray,
    wcs: Any,
    gaia_sources: list[gaia.GaiaSource],
    mjd: float,
    *,
    max_pm_mas_yr: float = 20.0,
    box_radius_px: int = 3,
    offset_warn_px: float = 0.5,
) -> dict[str, Any]:
    """Measure residual astrometric shift (dx, dy) of slow Gaia stars in one epoch."""
    ny, nx = image.shape
    noise = _robust_sigma(image)
    dxs: list[float] = []
    dys: list[float] = []

    for src in gaia_sources:
        pm = src.pm_total_mas_yr
        if pm is None or pm > max_pm_mas_yr:
            continue
        ra, dec = src.position_at(mjd)
        x_fits, y_fits = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
        ix, iy = int(round(x_fits)), int(round(y_fits))
        if (
            ix < box_radius_px
            or ix >= nx - box_radius_px
            or iy < box_radius_px
            or iy >= ny - box_radius_px
        ):
            continue
        cutout = image[
            iy - box_radius_px : iy + box_radius_px + 1,
            ix - box_radius_px : ix + box_radius_px + 1,
        ].astype(np.float64)
        if not np.isfinite(cutout).all():
            continue
        bg = float(np.median(cutout))
        sub = np.maximum(cutout - bg, 0.0)
        total = float(np.sum(sub))
        if total <= 0.0 or float(np.max(sub)) < 3.0 * noise:
            continue
        yy, xx = np.mgrid[
            iy - box_radius_px : iy + box_radius_px + 1,
            ix - box_radius_px : ix + box_radius_px + 1,
        ]
        cx = float(np.sum(xx * sub) / total)
        cy = float(np.sum(yy * sub) / total)
        dxs.append(cx - x_fits)
        # Flip sign for PNG y-axis (top = 0) so UI offsets match screen coordinates.
        dys.append(-(cy - y_fits))

    n_used = len(dxs)
    if n_used < 3:
        return {
            "stars_used": n_used,
            "median_dx_px": None,
            "median_dy_px": None,
            "rms_arcsec": None,
            "status": "insufficient_stars",
        }

    med_dx = float(np.median(dxs))
    med_dy = float(np.median(dys))
    rms_px = math.sqrt(float(np.mean([dx * dx + dy * dy for dx, dy in zip(dxs, dys)])))
    rms_arcsec = rms_px * config.PIXEL_SCALE_ARCSEC
    shift_px = math.hypot(med_dx, med_dy)
    return {
        "stars_used": n_used,
        "median_dx_px": round(med_dx, 3),
        "median_dy_px": round(med_dy, 3),
        "rms_arcsec": round(rms_arcsec, 3),
        "status": "offset_warning" if shift_px > offset_warn_px else "ok",
    }


def patch_crossmatch_summary(
    ra: float,
    dec: float,
    mjd: float,
    gaia_sources: list[gaia.GaiaSource],
    wise_sources: list[wise.WiseSource],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Nearest Gaia DR3 and CatWISE2020 match to (ra, dec) at ``mjd``."""
    gaia_info: dict[str, Any] | None = None
    if gaia_sources:
        best_g = gaia.nearest(gaia_sources, ra, dec, mjd)
        if best_g is not None:
            gsrc, gdist = best_g
            gaia_info = {
                "source_id": gsrc.source_id,
                "dist_arcsec": round(gdist, 3),
                "g_mag": None if gsrc.g_mag is None else round(gsrc.g_mag, 3),
                "bp_rp": None if gsrc.bp_rp is None else round(gsrc.bp_rp, 3),
                "pm_total_mas_yr": (
                    None if gsrc.pm_total_mas_yr is None else round(gsrc.pm_total_mas_yr, 2)
                ),
                "distance_pc": (
                    None if gsrc.distance_pc is None else round(gsrc.distance_pc, 2)
                ),
            }

    wise_info: dict[str, Any] | None = None
    if wise_sources:
        best_w = wise.nearest(wise_sources, ra, dec, mjd)
        if best_w is not None:
            wsrc, wdist = best_w
            wise_info = {
                "source_id": wsrc.source_id,
                "dist_arcsec": round(wdist, 3),
                "w1_mag": None if wsrc.w1_mag is None else round(wsrc.w1_mag, 3),
                "w2_mag": None if wsrc.w2_mag is None else round(wsrc.w2_mag, 3),
                "w1_w2_color": (
                    None if wsrc.w1_w2_color is None else round(wsrc.w1_w2_color, 3)
                ),
                "pm_total_mas_yr": (
                    None if wsrc.pm_total_mas_yr is None else round(wsrc.pm_total_mas_yr, 2)
                ),
            }

    return gaia_info, wise_info
