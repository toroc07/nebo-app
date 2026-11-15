"""Scientific metrics engine for SPHEREx cutouts, time series, and 17 spectral indices.

Implements the physical equations from METRICAS_Y_MODELOS.md in pure NumPy:
- Optimal ePSF-weighted photometry with mandatory 3% systematic floor (Eq. 19)
- Multi-epoch difference SNR maps and dipole symmetry
- Centroiding, proper motion, and Mahalanobis astrometric displacement
- Time-series variability (chi2_var, Lomb-Scargle, Stetson J, von Neumann eta)
- All 17 diagnostic SPHEREx spectral indices with analytical error propagation
- Global Confidence Score C_global in [0, 100]
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from . import config, science_catalogs


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def gaussian_epsf_kernel(
    size: int = 5,
    fwhm_px: float = 1.22,
    center_offset: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """Return a normalized 2D Gaussian ePSF kernel summing to 1.0."""
    radius = size // 2
    yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    sigma = max(0.35, fwhm_px / 2.35482)
    dx, dy = center_offset
    psf = np.exp(-(((xx - dx) ** 2 + (yy - dy) ** 2) / (2.0 * sigma * sigma)))
    total = float(np.sum(psf))
    return psf / total if total > 0.0 else psf


def extract_optimal_psf_photometry(
    image: np.ndarray,
    variance: np.ndarray,
    flags: np.ndarray | None = None,
    center_xy: tuple[int, int] | None = None,
    fwhm_px: float = 1.22,
) -> dict[str, Any]:
    """Compute ePSF-weighted flux, 3%-floored uncertainty, morphology, and flag purity.

    Uses a 5x5 local aperture around ``center_xy`` (defaulting to the image center)
    and an outer annulus for local background gradient estimation.
    """
    img = np.asarray(image, dtype=np.float64)
    var = np.asarray(variance, dtype=np.float64)
    h, w = img.shape
    cx, cy = center_xy if center_xy is not None else (w // 2, h // 2)

    r_ap = 2
    x0, x1 = max(0, cx - r_ap), min(w, cx + r_ap + 1)
    y0, y1 = max(0, cy - r_ap), min(h, cy + r_ap + 1)

    sub_img = img[y0:y1, x0:x1]
    sub_var = var[y0:y1, x0:x1]

    # Local annulus background (between r=3 and r=6 pixels)
    yy_full, xx_full = np.mgrid[0:h, 0:w]
    dist_full = np.hypot(xx_full - cx, yy_full - cy)
    annulus_mask = (dist_full >= 3.0) & (dist_full <= 6.5) & np.isfinite(img)
    if flags is not None:
        annulus_mask &= (np.asarray(flags, dtype=np.int64) & science_catalogs.MASK_BACKGROUND) == 0

    bg_vals = img[annulus_mask]
    bg_median = float(np.median(bg_vals)) if bg_vals.size > 0 else 0.0

    # Background spatial gradient on a 9x9 window
    gx0, gx1 = max(0, cx - 4), min(w, cx + 5)
    gy0, gy1 = max(0, cy - 4), min(h, cy + 5)
    bg_patch = np.where(np.isfinite(img[gy0:gy1, gx0:gx1]), img[gy0:gy1, gx0:gx1], bg_median)
    if bg_patch.shape[0] >= 3 and bg_patch.shape[1] >= 3:
        grad_y, grad_x = np.gradient(bg_patch)
        gx_rms = float(np.sqrt(np.mean(grad_x ** 2)))
        gy_rms = float(np.sqrt(np.mean(grad_y ** 2)))
    else:
        gx_rms, gy_rms = 0.0, 0.0
    bg_gradient_norm = math.hypot(gx_rms, gy_rms)
    bg_gradient_ratio = gy_rms / (gx_rms + 1e-6)

    # Photometry validity mask inside 5x5 aperture
    valid = np.isfinite(sub_img) & np.isfinite(sub_var) & (sub_var > 0.0)
    if flags is not None:
        sub_flags = np.asarray(flags[y0:y1, x0:x1], dtype=np.int64)
        p_clean_flags = float(np.mean(sub_flags == 0))
        f_artifact_flags = float(np.mean((sub_flags & science_catalogs.MASK_PHOTOMETRY) != 0))
        valid &= (sub_flags & science_catalogs.MASK_PHOTOMETRY) == 0
    else:
        p_clean_flags = float(np.mean(valid)) if valid.size > 0 else 0.0
        f_artifact_flags = 1.0 - p_clean_flags

    psf_full = gaussian_epsf_kernel(size=5, fwhm_px=fwhm_px)
    py0 = r_ap - (cy - y0)
    py1 = py0 + (y1 - y0)
    px0 = r_ap - (cx - x0)
    px1 = px0 + (x1 - x0)
    psf = psf_full[py0:py1, px0:px1]

    if not np.any(valid):
        return {
            "flux_hat": 0.0,
            "sigma_stat": 1.0,
            "sigma_reported": 1.0,
            "snr": 0.0,
            "q_fit_epsf": 99.0,
            "chi2_psf": 99.0,
            "c_80_20": 0.0,
            "c_psf": 0.0,
            "elongation_e": 0.0,
            "p_clean_flags": p_clean_flags,
            "f_artifact_flags": f_artifact_flags,
            "bg_median": bg_median,
            "bg_gradient_norm": bg_gradient_norm,
            "bg_gradient_ratio": bg_gradient_ratio,
            "n_valid_pixels": 0,
        }

    net = np.where(valid, sub_img - bg_median, 0.0)
    inv_var = np.where(valid, 1.0 / np.maximum(sub_var, 1e-12), 0.0)
    denom = float(np.sum((psf ** 2) * inv_var))
    if denom <= 0.0:
        flux_hat = 0.0
        sigma_stat = 1.0
    else:
        flux_hat = float(np.sum(psf * net * inv_var) / denom)
        sigma_stat = math.sqrt(1.0 / denom)

    sigma_reported = science_catalogs.compute_reported_sigma(flux_hat, sigma_stat)
    snr = flux_hat / sigma_reported if sigma_reported > 0.0 else 0.0

    model = flux_hat * psf
    resid = net - model
    n_valid = int(np.sum(valid))
    sigma_pix = np.sqrt(np.maximum(sub_var, 1e-12))
    q_fit_epsf = float(np.sum(np.abs(resid[valid]) / sigma_pix[valid]) / max(1, n_valid))
    dof = max(1, n_valid - 3)
    chi2_psf = float(np.sum(((resid[valid]) ** 2) * inv_var[valid]) / dof)

    # Radial concentration C_PSF and C_80/20
    yy_ap, xx_ap = np.mgrid[y0:y1, x0:x1]
    r_ap_grid = np.hypot(xx_ap - cx, yy_ap - cy)
    pos_net = np.where(valid & (net > 0.0), net, 0.0)
    total_pos = float(np.sum(pos_net))
    flux_r1 = float(np.sum(pos_net[r_ap_grid <= 1.05]))
    c_psf = (flux_r1 / total_pos) if total_pos > 0.0 else 0.0

    # Curve-of-growth r20 and r80
    if total_pos > 0.0:
        radii = np.sort(r_ap_grid[valid].ravel())
        order = np.argsort(r_ap_grid[valid].ravel())
        cum_flux = np.cumsum(pos_net[valid].ravel()[order]) / total_pos
        r20 = float(radii[np.searchsorted(cum_flux, 0.20, side="left")]) if radii.size else 0.5
        r80 = float(radii[np.searchsorted(cum_flux, 0.80, side="left")]) if radii.size else 1.5
        c_80_20 = 5.0 * math.log10(max(r80, 0.35) / max(r20, 0.20))
    else:
        c_80_20 = 0.0

    # Second-order central moments for elongation
    if total_pos > 0.0:
        mx = float(np.sum(xx_ap * pos_net) / total_pos)
        my = float(np.sum(yy_ap * pos_net) / total_pos)
        mxx = float(np.sum(((xx_ap - mx) ** 2) * pos_net) / total_pos)
        myy = float(np.sum(((yy_ap - my) ** 2) * pos_net) / total_pos)
        mxy = float(np.sum((xx_ap - mx) * (yy_ap - my) * pos_net) / total_pos)
        denom_m = mxx + myy
        elongation_e = (
            math.sqrt(max(0.0, (mxx - myy) ** 2 + 4.0 * mxy * mxy)) / denom_m
            if denom_m > 1e-9
            else 0.0
        )
    else:
        elongation_e = 0.0

    return {
        "flux_hat": round(flux_hat, 6),
        "sigma_stat": round(sigma_stat, 6),
        "sigma_reported": round(sigma_reported, 6),
        "snr": round(snr, 4),
        "q_fit_epsf": round(q_fit_epsf, 4),
        "chi2_psf": round(chi2_psf, 4),
        "c_80_20": round(c_80_20, 4),
        "c_psf": round(c_psf, 4),
        "elongation_e": round(elongation_e, 4),
        "p_clean_flags": round(p_clean_flags, 4),
        "f_artifact_flags": round(f_artifact_flags, 4),
        "bg_median": round(bg_median, 6),
        "bg_gradient_norm": round(bg_gradient_norm, 6),
        "bg_gradient_ratio": round(bg_gradient_ratio, 4),
        "n_valid_pixels": n_valid,
    }


def compute_difference_snr_map(
    img_t1: np.ndarray,
    var_t1: np.ndarray,
    img_t2: np.ndarray,
    var_t2: np.ndarray,
    pixel_scale_arcsec: float = config.PIXEL_SCALE_ARCSEC,
) -> dict[str, Any]:
    """Compute multi-epoch difference SNR map S_diff(x,y) and dipole diagnostics."""
    a = np.asarray(img_t1, dtype=np.float64)
    b = np.asarray(img_t2, dtype=np.float64)
    va = np.asarray(var_t1, dtype=np.float64)
    vb = np.asarray(var_t2, dtype=np.float64)

    diff = b - a
    comb_var = va + vb
    valid = np.isfinite(diff) & np.isfinite(comb_var) & (comb_var > 0.0)
    s_diff = np.where(valid, diff / np.sqrt(np.maximum(comb_var, 1e-12)), 0.0)

    if not np.any(valid):
        return {
            "z_mono": 0.0,
            "z_dipole": 0.0,
            "dipole_symmetry": 0.0,
            "angular_shift_arcsec": 0.0,
            "z_pos_max": 0.0,
            "z_neg_min": 0.0,
        }

    h, w = diff.shape
    cx, cy = w // 2, h // 2
    yy, xx = np.mgrid[0:h, 0:w]
    r_center = np.hypot(xx - cx, yy - cy)
    ap = valid & (r_center <= 2.5)
    z_mono = (
        float(np.sum(diff[ap]) / math.sqrt(max(1e-12, float(np.sum(comb_var[ap])))))
        if np.any(ap)
        else 0.0
    )

    pos_idx = int(np.argmax(s_diff))
    neg_idx = int(np.argmin(s_diff))
    py, px = divmod(pos_idx, w)
    ny, nx = divmod(neg_idx, w)
    z_pos_max = float(s_diff[py, px])
    z_neg_min = float(s_diff[ny, nx])

    if z_pos_max > 3.0 and z_neg_min < -3.0:
        z_dipole = math.sqrt(abs(z_pos_max * z_neg_min))
    else:
        z_dipole = 0.0

    # Local 3x3 fluxes around positive and negative poles
    def _pole_flux(px_c: int, py_c: int) -> float:
        x0, x1 = max(0, px_c - 1), min(w, px_c + 2)
        y0, y1 = max(0, py_c - 1), min(h, py_c + 2)
        patch = diff[y0:y1, x0:x1]
        m = valid[y0:y1, x0:x1]
        return float(np.sum(patch[m])) if np.any(m) else 0.0

    f_plus = abs(_pole_flux(px, py))
    f_minus = abs(_pole_flux(nx, ny))
    denom = f_plus + f_minus
    dipole_symmetry = (1.0 - abs(f_plus - f_minus) / denom) if denom > 0.0 else 0.0
    angular_shift_arcsec = pixel_scale_arcsec * math.hypot(px - nx, py - ny)

    return {
        "z_mono": round(z_mono, 4),
        "z_dipole": round(z_dipole, 4),
        "dipole_symmetry": round(max(0.0, min(1.0, dipole_symmetry)), 4),
        "angular_shift_arcsec": round(angular_shift_arcsec, 4),
        "z_pos_max": round(z_pos_max, 4),
        "z_neg_min": round(z_neg_min, 4),
    }


def _weighted_centroid(
    img: np.ndarray, var: np.ndarray
) -> tuple[tuple[float, float], np.ndarray]:
    """Compute flux-weighted centroid (x, y) and 2x2 positional covariance in pixel^2."""
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    valid = np.isfinite(img) & np.isfinite(var) & (var > 0.0) & (img > 0.0)
    if not np.any(valid):
        return (w / 2.0, h / 2.0), np.eye(2, dtype=np.float64) * 0.25

    weights = np.where(valid, img / np.maximum(var, 1e-12), 0.0)
    w_sum = float(np.sum(weights))
    if w_sum <= 0.0:
        return (w / 2.0, h / 2.0), np.eye(2, dtype=np.float64) * 0.25

    cx = float(np.sum(xx * weights) / w_sum)
    cy = float(np.sum(yy * weights) / w_sum)
    # Positional variance scaled by inverse SNR^2 (floor 0.02 px^2)
    snr_tot = float(np.sum(img[valid]) / math.sqrt(max(1e-12, float(np.sum(var[valid])))))
    pos_var = max(0.015, 1.0 / max(1.0, snr_tot ** 2))
    cov = np.array([[pos_var, 0.0], [0.0, pos_var]], dtype=np.float64)
    return (cx, cy), cov


def compute_centroid_and_mahalanobis(
    img_t1: np.ndarray,
    var_t1: np.ndarray,
    img_t2: np.ndarray,
    var_t2: np.ndarray,
    mjd_t1: float,
    mjd_t2: float,
    pixel_scale_arcsec: float = config.PIXEL_SCALE_ARCSEC,
) -> dict[str, Any]:
    """Compute astrometric shift, proper motion, and Mahalanobis distance D_M."""
    c1, cov1 = _weighted_centroid(np.asarray(img_t1, dtype=np.float64), np.asarray(var_t1, dtype=np.float64))
    c2, cov2 = _weighted_centroid(np.asarray(img_t2, dtype=np.float64), np.asarray(var_t2, dtype=np.float64))
    delta = np.array([c2[0] - c1[0], c2[1] - c1[1]], dtype=np.float64)
    cov_sum = cov1 + cov2
    inv_cov = np.linalg.pinv(cov_sum)
    dm = float(math.sqrt(max(0.0, float(delta.T @ inv_cov @ delta))))

    shift_px = float(math.hypot(delta[0], delta[1]))
    shift_arcsec = shift_px * pixel_scale_arcsec
    dt_yr = max(1e-4, abs(mjd_t2 - mjd_t1) / 365.25)
    # East is left in North-up/East-left orientation -> +x is West (-RA)
    pm_ra_mas_yr = (-delta[0] * pixel_scale_arcsec * 1000.0) / dt_yr
    pm_dec_mas_yr = (-delta[1] * pixel_scale_arcsec * 1000.0) / dt_yr
    pm_total_mas_yr = math.hypot(pm_ra_mas_yr, pm_dec_mas_yr)

    return {
        "centroid_t1_px": [round(c1[0], 3), round(c1[1], 3)],
        "centroid_t2_px": [round(c2[0], 3), round(c2[1], 3)],
        "shift_arcsec": round(shift_arcsec, 4),
        "pm_ra_mas_yr": round(pm_ra_mas_yr, 2),
        "pm_dec_mas_yr": round(pm_dec_mas_yr, 2),
        "pm_total_mas_yr": round(pm_total_mas_yr, 2),
        "mahalanobis_dm": round(dm, 4),
        "is_significant_motion": dm >= 3.0,
    }


def compute_variability_metrics(
    times_mjd: list[float] | np.ndarray,
    fluxes: list[float] | np.ndarray,
    sigmas: list[float] | np.ndarray,
    fluxes_band_b: list[float] | np.ndarray | None = None,
    sigmas_band_b: list[float] | np.ndarray | None = None,
) -> dict[str, Any]:
    """Compute chi2_var, vectorized Lomb-Scargle peak, Stetson J, and von Neumann eta."""
    t = np.asarray(times_mjd, dtype=np.float64)
    y = np.asarray(fluxes, dtype=np.float64)
    s = np.asarray(sigmas, dtype=np.float64)
    valid = np.isfinite(t) & np.isfinite(y) & np.isfinite(s) & (s > 0.0)
    t, y, s = t[valid], y[valid], s[valid]
    n = int(t.size)

    if n < 2:
        return {
            "n_epochs": n,
            "weighted_mean_mjy": float(y[0]) if n == 1 else 0.0,
            "chi2_var_reduced": 0.0,
            "stetson_j": 0.0,
            "von_neumann_eta": 2.0,
            "lomb_scargle_power": 0.0,
            "lomb_scargle_period_days": None,
            "is_variable": False,
        }

    order = np.argsort(t)
    t, y, s = t[order], y[order], s[order]

    w = 1.0 / (s ** 2)
    mean_w = float(np.sum(w * y) / np.sum(w))
    chi2_var = float(np.sum(((y - mean_w) / s) ** 2) / max(1, n - 1))

    # von Neumann eta (ratio of mean square successive difference to variance)
    var_y = float(np.var(y, ddof=1)) if n > 1 else 0.0
    if var_y > 1e-18 and n > 2:
        eta = float(np.mean(np.diff(y) ** 2) / var_y)
    else:
        eta = 2.0

    # Stetson J index
    delta_a = math.sqrt(n / max(1, n - 1)) * ((y - mean_w) / s)
    if fluxes_band_b is not None and sigmas_band_b is not None:
        yb = np.asarray(fluxes_band_b, dtype=np.float64)[valid][order]
        sb = np.asarray(sigmas_band_b, dtype=np.float64)[valid][order]
        wb = 1.0 / np.maximum(sb ** 2, 1e-12)
        mean_wb = float(np.sum(wb * yb) / np.sum(wb))
        delta_b = math.sqrt(n / max(1, n - 1)) * ((yb - mean_wb) / np.maximum(sb, 1e-6))
        pk = delta_a * delta_b
    else:
        pk = delta_a[:-1] * delta_a[1:]
    stetson_j = float(np.mean(np.sign(pk) * np.sqrt(np.abs(pk)))) if pk.size > 0 else 0.0

    # Generalized Lomb-Scargle periodogram over physical periods [0.1, 400] days
    span = max(1.0, float(t[-1] - t[0]))
    periods = np.geomspace(max(0.1, span / 200.0), max(300.0, span * 2.0), 320)
    omegas = (2.0 * math.pi) / periods
    yc = y - mean_w
    yc_norm = float(np.sum(w * (yc ** 2)))
    best_power = 0.0
    best_period: float | None = None

    if yc_norm > 1e-18 and n >= 4:
        phase = omegas[:, None] * t[None, :]
        cos_p = np.cos(phase)
        sin_p = np.sin(phase)
        c_sum = np.sum(w[None, :] * (cos_p ** 2), axis=1)
        s_sum = np.sum(w[None, :] * (sin_p ** 2), axis=1)
        yc_cos = np.sum(w[None, :] * yc[None, :] * cos_p, axis=1)
        yc_sin = np.sum(w[None, :] * yc[None, :] * sin_p, axis=1)
        powers = ((yc_cos ** 2) / np.maximum(c_sum, 1e-12) + (yc_sin ** 2) / np.maximum(s_sum, 1e-12)) / yc_norm
        idx_max = int(np.argmax(powers))
        best_power = float(min(1.0, max(0.0, powers[idx_max])))
        best_period = float(periods[idx_max])

    return {
        "n_epochs": n,
        "weighted_mean_mjy": round(mean_w, 6),
        "chi2_var_reduced": round(chi2_var, 4),
        "stetson_j": round(stetson_j, 4),
        "von_neumann_eta": round(eta, 4),
        "lomb_scargle_power": round(best_power, 4),
        "lomb_scargle_period_days": round(best_period, 3) if best_period is not None else None,
        "is_variable": chi2_var > 3.0,
    }


def compute_global_confidence_score(
    snr: float,
    dipole_symmetry: float = 1.0,
    angular_shift_px: float = 1.0,
    active_flag_names: list[str] | tuple[str, ...] = (),
    q_fit_epsf: float = 1.0,
    is_stationary: bool = False,
) -> dict[str, Any]:
    """Compute Section 4.3 Global Confidence Score C_global in [0, 100]."""
    s_snr = 1.0 / (1.0 + math.exp(-0.8 * (snr - 4.0)))
    if is_stationary:
        s_dipole = 1.0
    else:
        in_range = 1.0 if 0.4 <= angular_shift_px <= 12.0 else 0.75
        s_dipole = max(0.0, min(1.0, dipole_symmetry)) * in_range

    penalties = {
        "SNOWBALL": 1.0,
        "PERSIST": 0.8,
        "GHOST": 0.9,
        "HOT": 0.7,
        "STREAK": 1.0,
        "SUR_ERROR": 1.0,
    }
    total_pen = sum(penalties.get(name.upper(), 0.2) for name in active_flag_names)
    s_flags = max(0.0, 1.0 - total_pen)
    s_psf = math.exp(-((q_fit_epsf - 1.0) ** 2) / (2.0 * (0.35 ** 2)))
    c_global = 100.0 * s_snr * s_dipole * s_flags * s_psf

    return {
        "c_global": round(c_global, 2),
        "s_snr": round(s_snr, 4),
        "s_dipole": round(s_dipole, 4),
        "s_flags": round(s_flags, 4),
        "s_psf": round(s_psf, 4),
    }


def compute_band_coadds(
    flux_mjy: list[float | None],
    sigma_mjy: list[float | None],
    valid_mask: list[bool],
) -> dict[str, dict[str, float | int | None]]:
    """Compute inverse-variance weighted band co-adds for SPHEREx detectors 1..6."""
    coadds: dict[str, dict[str, float | int | None]] = {}
    for band in range(1, 7):
        weights: list[float] = []
        values: list[float] = []
        for ch in science_catalogs.SPHEREX_102_CHANNELS:
            if ch.band != band or ch.is_blankch:
                continue
            i = ch.channel_id - 1
            f = flux_mjy[i]
            s = sigma_mjy[i]
            if not valid_mask[i] or f is None or s is None or not (math.isfinite(f) and math.isfinite(s)) or s <= 0.0:
                continue
            w = 1.0 / (s * s)
            weights.append(w)
            values.append(f)

        key = f"band_{band}"
        if not weights:
            coadds[key] = {"flux_mjy": None, "sigma_mjy": None, "n_channels": 0}
        else:
            w_sum = sum(weights)
            f_stack = sum(w * v for w, v in zip(weights, values)) / w_sum
            s_stat = math.sqrt(1.0 / w_sum)
            s_rep = science_catalogs.compute_reported_sigma(f_stack, s_stat)
            coadds[key] = {
                "flux_mjy": round(f_stack, 6),
                "sigma_mjy": round(s_rep, 6),
                "n_channels": len(weights),
            }
    return coadds


def _channel_value(
    channel_id: int,
    flux_mjy: list[float | None],
    sigma_mjy: list[float | None],
    valid_mask: list[bool],
) -> tuple[float, float, float, float] | None:
    """Return (lambda_c, delta_lambda, flux, sigma) for a valid non-BLANKCH channel."""
    if channel_id in science_catalogs.BLANK_CHANNELS:
        return None
    i = channel_id - 1
    if i < 0 or i >= 102 or not valid_mask[i]:
        return None
    f = flux_mjy[i]
    s = sigma_mjy[i]
    if f is None or s is None or not (math.isfinite(f) and math.isfinite(s)) or s <= 0.0:
        return None
    ch = science_catalogs.CHANNELS_BY_ID[channel_id]
    return ch.lambda_c_um, ch.lambda_max_um - ch.lambda_min_um, float(f), float(s)


def _eval_single_index(
    spec: science_catalogs.SpectralIndexSpec,
    flux_mjy: list[float | None],
    sigma_mjy: list[float | None],
    valid_mask: list[bool],
    band_coadds: dict[str, dict[str, float | int | None]],
) -> dict[str, Any]:
    """Evaluate one of the 17 SPHEREx spectral indices with analytical uncertainty."""
    invalid = {
        "index_code": spec.index_code,
        "value": None,
        "uncertainty": None,
        "snr": None,
        "is_significant_3s": False,
        "is_valid": False,
        "details_json": {"formula_type": spec.formula_type, "reason": "missing_channels"},
    }

    if spec.formula_type == "NSDI":
        b_a = band_coadds.get(f"band_{spec.band_a}", {})
        b_b = band_coadds.get(f"band_{spec.band_b}", {})
        fa, sa = b_a.get("flux_mjy"), b_a.get("sigma_mjy")
        fb, sb = b_b.get("flux_mjy"), b_b.get("sigma_mjy")
        if fa is None or sa is None or fb is None or sb is None:
            return invalid
        # Regularize negative noise floors per Section 2.3
        fa_reg = max(float(fa), 3.0 * float(sa))
        fb_reg = max(float(fb), 3.0 * float(sb))
        val, unc = science_catalogs.compute_nsdi(fa_reg, float(sa), fb_reg, float(sb))
        if val is None or unc is None or unc <= 0.0:
            return invalid
        snr = abs(val) / unc
        return {
            "index_code": spec.index_code,
            "value": round(val, 6),
            "uncertainty": round(unc, 6),
            "snr": round(snr, 4),
            "is_significant_3s": snr >= 3.0,
            "is_valid": True,
            "details_json": {"formula_type": "NSDI", "band_a": spec.band_a, "band_b": spec.band_b},
        }

    if spec.formula_type == "COLOR_RATIO":
        b_a = band_coadds.get(f"band_{spec.band_a}", {})
        b_b = band_coadds.get(f"band_{spec.band_b}", {})
        fa, sa = b_a.get("flux_mjy"), b_a.get("sigma_mjy")
        fb, sb = b_b.get("flux_mjy"), b_b.get("sigma_mjy")
        if fa is None or sa is None or fb is None or sb is None:
            return invalid
        fb_reg = float(fb)
        if abs(fb_reg) < 3.0 * float(sb):
            sign = 1.0 if fb_reg >= 0.0 else -1.0
            fb_reg = fb_reg + sign * 3.0 * float(sb)
        val, unc = science_catalogs.compute_color_ratio(float(fa), float(sa), fb_reg, float(sb))
        if val is None or unc is None or unc <= 0.0:
            return invalid
        snr = abs(val) / unc
        return {
            "index_code": spec.index_code,
            "value": round(val, 6),
            "uncertainty": round(unc, 6),
            "snr": round(snr, 4),
            "is_significant_3s": snr >= 3.0,
            "is_valid": True,
            "details_json": {"formula_type": "COLOR_RATIO", "band_a": spec.band_a, "band_b": spec.band_b},
        }

    if spec.blue_anchor_channel is None or spec.red_anchor_channel is None:
        return invalid

    a1 = _channel_value(spec.blue_anchor_channel, flux_mjy, sigma_mjy, valid_mask)
    a2 = _channel_value(spec.red_anchor_channel, flux_mjy, sigma_mjy, valid_mask)
    if a1 is None or a2 is None:
        return invalid
    lam1, _, f1, s1 = a1
    lam2, _, f2, s2 = a2
    if lam2 == lam1:
        return invalid

    feats = [_channel_value(cid, flux_mjy, sigma_mjy, valid_mask) for cid in spec.feature_channels]
    valid_feats = [f for f in feats if f is not None]
    if not valid_feats:
        return invalid

    if spec.formula_type == "EQUIV_WIDTH_W":
        w_val = 0.0
        var_k_sum = 0.0
        d_f1 = 0.0
        d_f2 = 0.0
        for lam_k, dlam_k, fk, sk in valid_feats:
            wk = (lam_k - lam1) / (lam2 - lam1)
            f_cont = (1.0 - wk) * f1 + wk * f2
            if f_cont <= 0.0:
                return invalid
            w_val += (1.0 - fk / f_cont) * dlam_k
            var_k_sum += ((dlam_k / f_cont) ** 2) * (sk ** 2)
            d_f1 += (fk * dlam_k * (1.0 - wk)) / (f_cont ** 2)
            d_f2 += (fk * dlam_k * wk) / (f_cont ** 2)
        unc = math.sqrt(var_k_sum + (d_f1 * s1) ** 2 + (d_f2 * s2) ** 2)
        snr = abs(w_val) / unc if unc > 0.0 else 0.0
        return {
            "index_code": spec.index_code,
            "value": round(w_val, 6),
            "uncertainty": round(unc, 6),
            "snr": round(snr, 4),
            "is_significant_3s": snr >= 3.0,
            "is_valid": True,
            "details_json": {"formula_type": "EQUIV_WIDTH_W", "unit": "um"},
        }

    # Combine multi-channel feature cores (e.g. IND_CO_23, IND_CO2_42) via inverse-variance mean
    if len(valid_feats) == 1:
        lam0, _, f0, s0 = valid_feats[0]
    else:
        inv_vs = [1.0 / (f[3] ** 2) for f in valid_feats]
        w_sum = sum(inv_vs)
        lam0 = sum(f[0] * iv for f, iv in zip(valid_feats, inv_vs)) / w_sum
        f0 = sum(f[2] * iv for f, iv in zip(valid_feats, inv_vs)) / w_sum
        s0 = math.sqrt(1.0 / w_sum)

    # BLUE_EXTRAP_RATIO projects linearly from blue anchors (45, 47) past 2.189 um to avoid BLANKCH 51-52
    w_interp = (lam0 - lam1) / (lam2 - lam1)
    f_cont = (1.0 - w_interp) * f1 + w_interp * f2
    var_cont = ((1.0 - w_interp) ** 2) * (s1 ** 2) + (w_interp ** 2) * (s2 ** 2)

    if spec.formula_type == "LINE_FLUX_DELTA_F":
        val = f0 - f_cont
        unc = math.sqrt((s0 ** 2) + var_cont)
    elif spec.formula_type in ("DEPTH_D", "BLUE_EXTRAP_RATIO"):
        if f_cont <= 0.0:
            return invalid
        val = 1.0 - (f0 / f_cont)
        unc = math.sqrt((s0 ** 2) / (f_cont ** 2) + ((f0 ** 2) / (f_cont ** 4)) * var_cont)
    else:
        return invalid

    snr = abs(val) / unc if unc > 0.0 else 0.0
    return {
        "index_code": spec.index_code,
        "value": round(val, 6),
        "uncertainty": round(unc, 6),
        "snr": round(snr, 4),
        "is_significant_3s": snr >= 3.0,
        "is_valid": True,
        "details_json": {"formula_type": spec.formula_type, "lambda_eff_um": round(lam0, 4)},
    }


def compute_all_17_spectral_indices(spectrum: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute all 17 SPHEREx spectral indices while strictly keeping BLANKCH 51-52 null."""
    # Always 102 entries, so a short or long list cannot index out of range (missing = invalid).
    def channels(key: str, missing: Any) -> list[Any]:
        values = list(spectrum.get(key) or [])[:102]
        return values + [missing] * (102 - len(values))

    flux_mjy = channels("flux_mjy", None)
    sigma_mjy = channels("sigma_reported_mjy", None)
    valid_mask = channels("valid_mask", False)
    for blank_ch in science_catalogs.BLANK_CHANNELS:
        idx = blank_ch - 1
        flux_mjy[idx] = None
        sigma_mjy[idx] = None
        valid_mask[idx] = False

    band_coadds = spectrum.get("band_coadd_flux_mjy") or compute_band_coadds(
        flux_mjy, sigma_mjy, valid_mask
    )
    return [
        _eval_single_index(spec, flux_mjy, sigma_mjy, valid_mask, band_coadds)
        for spec in science_catalogs.SPHEREX_17_INDICES
    ]
