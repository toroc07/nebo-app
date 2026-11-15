"""Cross-matching, epoch-change attribution, and Gaia astrometric alignment checks.

Pure NumPy + Astropy WCS routines that operate on the float32 epoch arrays produced by
``imaging.to_npz`` and the catalog sources from ``gaia.py`` and ``wise.py``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
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


# Change detection between two epoch co-adds.
#
# SPHEREx epochs of one field are not photometric twins: each epoch sees a star through a
# different part of the linear variable filter (a slightly different wavelength), the co-adds
# are undersampled nearest-neighbour stacks whose star centroids sit at different sub-pixel
# phases, and the overall flux scale can drift by a few per cent. A raw ``B - A`` therefore
# leaves a residual at almost every star. Before differencing, epoch B is scaled to A with the
# clipped aperture-flux ratio of the field's stars, the sharper PSF is matched to the broader one
# and both epochs are smoothed by 1 px more (PSF homogenisation). The threshold stays a plain
# k-sigma on the robust noise of the resulting difference. Residuals that remain on a static,
# catalogued star whose flux is consistent across epochs are labelled as likely systematics in
# ``classify_changes``.
MAX_CANDIDATES = 25
# Detections kept before classification, so systematics cannot crowd real changes out of the list.
MAX_DETECTIONS = 200
DEFAULT_SNR_THRESHOLD = 5.0
# Extra Gaussian blur (px) on top of the broader of the two PSFs. Measured on Barnard's Star and
# Eps Indi B (detector 3): 1 px roughly halves the star residuals and keeps both movers detected.
HOMOGENISE_SIGMA_PX = 1.0
# Stars used for the flux scale: local maxima of the mean image above this many robust sigmas.
SCALE_STAR_SIGMA = 20.0
MIN_SCALE_STARS = 3
# A scale outside this range means the stars are not comparable (e.g. one epoch is mostly
# empty); B is then left unscaled.
SCALE_LIMITS = (0.5, 2.0)
APERTURE_RADIUS_PX = 2
# Gaussian kernels (px) tried when matching the sharper epoch's PSF to the broader one.
PSF_MATCH_KERNELS_PX = tuple(round(0.05 * i, 2) for i in range(1, 25))


@dataclass
class Normalisation:
    """How epoch B was matched to epoch A before differencing."""

    flux_scale: float  # B was multiplied by this.
    scale_stars: int  # Stars behind the scale (0: not enough, B left as it was).
    psf_sigma_a_px: float | None  # Gaussian-equivalent PSF sigma of each epoch (star moments).
    psf_sigma_b_px: float | None
    psf_match_kernel_px: float  # Gaussian sigma applied to the sharper epoch (0: PSFs matched).
    psf_matched_epoch: str | None  # "a" or "b": which epoch got that kernel.
    smoothing_sigma_px: float  # Then both epochs were smoothed by this much (0: no smoothing).
    noise_sigma: float  # Robust sigma of the normalised difference (MJy/sr).

    def payload(self) -> dict[str, Any]:
        def r(value: float | None, digits: int = 3) -> float | None:
            return None if value is None else round(value, digits)

        return {
            "flux_scale": r(self.flux_scale, 4),
            "scale_stars": self.scale_stars,
            "psf_sigma_a_px": r(self.psf_sigma_a_px),
            "psf_sigma_b_px": r(self.psf_sigma_b_px),
            "psf_match_kernel_px": r(self.psf_match_kernel_px),
            "psf_matched_epoch": self.psf_matched_epoch,
            "smoothing_sigma_px": r(self.smoothing_sigma_px),
            "noise_sigma": r(self.noise_sigma, 6),
        }


@dataclass
class ChangeSearch:
    detections: list[dict[str, Any]]
    normalisation: Normalisation
    # Background-subtracted epochs, B already scaled to A (not convolved): for photometry.
    image_a: np.ndarray
    image_b: np.ndarray


def gaussian_smooth(image: np.ndarray, sigma_px: float) -> np.ndarray:
    """Separable Gaussian convolution that ignores NaN pixels and keeps them NaN."""
    if sigma_px <= 0:
        return image.astype(np.float64, copy=True)

    def kernel_matrix(n: int) -> np.ndarray:
        # Row i holds the (unnormalised) Gaussian weights of every pixel around pixel i.
        offsets = np.arange(n)[:, None] - np.arange(n)[None, :]
        matrix = np.exp(-(offsets**2) / (2.0 * sigma_px**2))
        matrix[np.abs(offsets) > max(1, math.ceil(3.0 * sigma_px))] = 0.0
        return matrix

    rows, cols = kernel_matrix(image.shape[0]), kernel_matrix(image.shape[1])
    valid = np.isfinite(image)
    # Normalised convolution: dividing by the convolved mask makes missing pixels and the
    # image border not count, instead of pulling the neighbourhood towards zero.
    weight = rows @ valid.astype(np.float64) @ cols.T
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (rows @ np.where(valid, image, 0.0) @ cols.T) / weight
    out[~valid] = np.nan
    return out


def _local_maxima(values: np.ndarray, threshold: float, edge: int = 1) -> list[tuple[float, int, int]]:
    """(value, x, y) of pixels >= threshold that are the maximum of their 3x3 box, highest first."""
    filled = np.where(np.isfinite(values), values, -np.inf)
    padded = np.pad(filled, 1, constant_values=-np.inf)
    neighbourhood = np.lib.stride_tricks.sliding_window_view(padded, (3, 3)).max(axis=(2, 3))
    peak = (filled >= threshold) & (filled >= neighbourhood)
    if edge > 0:
        peak[:edge, :] = False
        peak[-edge:, :] = False
        peak[:, :edge] = False
        peak[:, -edge:] = False
    ys, xs = np.nonzero(peak)
    return sorted(((float(filled[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)


def aperture_photometry(
    image: np.ndarray, x: int, y: int, radius: int = APERTURE_RADIUS_PX
) -> tuple[float, float]:
    """Background-subtracted box flux and Gaussian-equivalent sigma (px) of a star at (x, y).

    The box is clipped to the image; the background is the median of a 1 px ring around it.
    Returns NaN when any pixel in the box has no value (a saturated core or no coverage).
    """
    ny, nx = image.shape
    x0, x1 = max(0, x - radius), min(nx, x + radius + 1)
    y0, y1 = max(0, y - radius), min(ny, y + radius + 1)
    box = image[y0:y1, x0:x1]
    if box.size == 0 or not np.isfinite(box).all():
        return math.nan, math.nan
    ry0, rx0 = max(0, y0 - 1), max(0, x0 - 1)
    ring = image[ry0 : y1 + 1, rx0 : x1 + 1].astype(np.float64)
    ring[y0 - ry0 : y1 - ry0, x0 - rx0 : x1 - rx0] = np.nan
    ring = ring[np.isfinite(ring)]
    background = float(np.median(ring)) if ring.size else 0.0
    sub = box - background
    flux = float(sub.sum())
    weight = np.maximum(sub, 0.0)
    total = float(weight.sum())
    if total <= 0.0:
        return flux, math.nan
    yy, xx = np.mgrid[y0:y1, x0:x1]
    cx, cy = float((xx * weight).sum() / total), float((yy * weight).sum() / total)
    second = float((((xx - cx) ** 2 + (yy - cy) ** 2) * weight).sum() / total)
    return flux, math.sqrt(second / 2.0)


def _flux_scale(fluxes_a: list[float], fluxes_b: list[float]) -> tuple[float, list[int]]:
    """Factor that brings B's star fluxes onto A's, and the indices of the stars behind it.

    Stars whose ratio is far from the median (movers, variables, blends) are dropped; the
    scale is then the ratio of the summed fluxes, so it is set mostly by the bright stars whose
    residuals matter most. (1.0, []) when there are too few usable stars.
    """
    usable = [
        i
        for i, (fa, fb) in enumerate(zip(fluxes_a, fluxes_b))
        if math.isfinite(fa) and math.isfinite(fb) and fa > 0 and fb > 0
    ]
    if len(usable) < MIN_SCALE_STARS:
        return 1.0, []
    ratios = np.array([fluxes_a[i] / fluxes_b[i] for i in usable])
    median = float(np.median(ratios))
    spread = max(1.4826 * float(np.median(np.abs(ratios - median))), 0.01 * median)
    kept = [i for i, ratio in zip(usable, ratios) if abs(ratio - median) <= 3.0 * spread]
    if len(kept) < MIN_SCALE_STARS:
        return 1.0, []
    scale = sum(fluxes_a[i] for i in kept) / sum(fluxes_b[i] for i in kept)
    if not SCALE_LIMITS[0] <= scale <= SCALE_LIMITS[1]:
        return 1.0, []
    return float(scale), kept


def _psf_match_kernel(
    a: np.ndarray, b: np.ndarray, stars: list[tuple[int, int]]
) -> tuple[float, str | None]:
    """Gaussian sigma (px) that, applied to the sharper epoch, best matches the other one.

    Tries each kernel in ``PSF_MATCH_KERNELS_PX`` on A and on B and keeps the one with the
    smallest squared residual over the star stamps, relative to the stars' squared flux (so the
    bright stars, whose residuals matter, set it and noise on faint ones does not).
    (0.0, None) when the PSFs already match best or there are too few clean stars.
    """
    ny, nx = a.shape
    r = APERTURE_RADIUS_PX + 1
    stamps = []
    for x, y in stars:
        if r <= x < nx - r and r <= y < ny - r:
            box = (slice(y - r, y + r + 1), slice(x - r, x + r + 1))
            if np.isfinite(a[box]).all() and np.isfinite(b[box]).all():
                norm = float(np.sum(np.abs(a[box]))) ** 2
                if norm > 0:
                    stamps.append((box, norm))
    if len(stamps) < MIN_SCALE_STARS:
        return 0.0, None

    total_norm = sum(norm for _, norm in stamps)

    def cost(first: np.ndarray, second: np.ndarray) -> float:
        return sum(float(np.sum((second[box] - first[box]) ** 2)) for box, _ in stamps) / total_norm

    best: tuple[float, float, str | None] = (cost(a, b), 0.0, None)
    for sigma in PSF_MATCH_KERNELS_PX:
        for option in (
            (cost(gaussian_smooth(a, sigma), b), sigma, "a"),
            (cost(a, gaussian_smooth(b, sigma)), sigma, "b"),
        ):
            if option[0] < best[0]:
                best = option
    return best[1], best[2]


def find_epoch_changes(
    image_a: np.ndarray,
    image_b: np.ndarray,
    wcs: Any,
    *,
    snr_threshold: float = DEFAULT_SNR_THRESHOLD,
    min_separation_px: int = 3,
    max_detections: int = MAX_DETECTIONS,
    normalise: bool = True,
    homogenise_sigma_px: float = HOMOGENISE_SIGMA_PX,
) -> ChangeSearch | None:
    """Significant point-like changes in ``B - A`` after flux scaling and PSF homogenisation.

    ``normalise=False`` is the plain difference (no scale, no convolution), kept for comparison.
    Returns None when the images cannot be compared (different shapes or no data).
    """
    if image_a.shape != image_b.shape:
        return None
    a = image_a.astype(np.float64)
    b = image_b.astype(np.float64)
    if not (np.isfinite(a).any() and np.isfinite(b).any()):
        return None
    a = a - float(np.nanmedian(a))
    b = b - float(np.nanmedian(b))

    scale, scale_stars = 1.0, 0
    sigma_a = sigma_b = None
    kernel, matched = 0.0, None
    a_cmp, b_cmp = a, b
    smoothing = 0.0
    if normalise:
        mean = 0.5 * (a + b)
        stars = [
            (x, y)
            for _, x, y in _local_maxima(
                mean, SCALE_STAR_SIGMA * _robust_sigma(mean), edge=APERTURE_RADIUS_PX
            )
        ]
        phot_a = [aperture_photometry(a, x, y) for x, y in stars]
        phot_b = [aperture_photometry(b, x, y) for x, y in stars]
        scale, kept = _flux_scale([f for f, _ in phot_a], [f for f, _ in phot_b])
        scale_stars = len(kept)
        b = b * scale
        widths_a = [w for _, w in phot_a if math.isfinite(w)]
        widths_b = [w for _, w in phot_b if math.isfinite(w)]
        sigma_a = float(np.median(widths_a)) if widths_a else None
        sigma_b = float(np.median(widths_b)) if widths_b else None
        # Match the sharper PSF to the broader one (on the stars that agree in flux, so a mover
        # or a variable does not steer it), then smooth both by the same extra kernel.
        kernel, matched = _psf_match_kernel(a, b, [stars[i] for i in kept])
        smoothing = homogenise_sigma_px
        # Applied in two steps, exactly as the kernel was fitted: on a pixel grid a sub-pixel
        # kernel is not a true Gaussian, so adding the two in quadrature would not match.
        a_cmp = gaussian_smooth(gaussian_smooth(a, kernel) if matched == "a" else a, smoothing)
        b_cmp = gaussian_smooth(gaussian_smooth(b, kernel) if matched == "b" else b, smoothing)

    diff = b_cmp - a_cmp
    finite = np.isfinite(diff)
    if not finite.any():
        return None
    centered = diff - float(np.median(diff[finite]))
    sigma = _robust_sigma(centered)
    abs_snr = np.abs(centered) / sigma
    normalisation = Normalisation(
        scale, scale_stars, sigma_a, sigma_b, kernel, matched, smoothing, sigma
    )

    kept: list[tuple[float, int, int]] = []
    for snr, x, y in _local_maxima(abs_snr, snr_threshold):
        if any(math.hypot(x - kx, y - ky) < min_separation_px for _, kx, ky in kept):
            continue
        kept.append((snr, x, y))
        if len(kept) >= max_detections:
            break

    ny = diff.shape[0]
    detections: list[dict[str, Any]] = []
    for snr, x_fits, y_fits in kept:
        ra, dec = (float(v) for v in wcs.pixel_to_world_values(x_fits, y_fits))
        delta = float(centered[y_fits, x_fits])
        detections.append(
            {
                "ra": round(ra % 360.0, 7),
                "dec": round(dec, 7),
                "x": int(x_fits),
                "y": int(ny - 1 - y_fits),
                "snr": round(snr, 2),
                "delta_flux": round(delta, 5),
                "polarity": "positive" if delta >= 0 else "negative",
            }
        )
    return ChangeSearch(detections, normalisation, a, b)


def detect_epoch_changes(
    image_a: np.ndarray,
    image_b: np.ndarray,
    wcs: Any,
    *,
    snr_threshold: float = DEFAULT_SNR_THRESHOLD,
    min_separation_px: int = 3,
    max_candidates: int = MAX_CANDIDATES,
    normalise: bool = True,
) -> list[dict[str, Any]]:
    """Detections of ``find_epoch_changes`` only, strongest first (FITS orientation in, PNG y out)."""
    search = find_epoch_changes(
        image_a,
        image_b,
        wcs,
        snr_threshold=snr_threshold,
        min_separation_px=min_separation_px,
        max_detections=max_candidates,
        normalise=normalise,
    )
    return [] if search is None else search.detections


# A residual on a catalogued star is attributed to it within this radius: after PSF
# homogenisation the two lobes of a sub-pixel or proper-motion dipole sit up to ~2 px apart.
SYSTEMATIC_MATCH_RADIUS_PX = 2.0
# A Gaia star "consistent across epochs": it moves less than this between the two dates...
STATIC_MAX_SHIFT_PX = 0.5
# ...and its aperture flux changes by less than this fraction. Per-star flux ratios between
# SPHEREx epochs scatter by ~10-20 % because each epoch samples a slightly different wavelength
# through the linear variable filter (measured on Barnard's Star detector 3, interquartile range
# 0.91-1.13); 30 % keeps real large-amplitude variability out of the systematic label.
SYSTEMATIC_MAX_REL_CHANGE = 0.3
# The star must be clearly detected in its aperture, else its "consistent flux" means nothing.
SYSTEMATIC_MIN_STAR_SNR = 5.0

CHANGE_CLASSES = ("candidate_signal", "catalogued_object", "catalogued_systematic")


def _gaia_payload(src: gaia.GaiaSource, dist: float) -> dict[str, Any]:
    return {
        "source_id": src.source_id,
        "dist_arcsec": round(dist, 3),
        "g_mag": None if src.g_mag is None else round(src.g_mag, 3),
        "pm_total_mas_yr": (
            None if src.pm_total_mas_yr is None else round(src.pm_total_mas_yr, 2)
        ),
    }


def _systematic_check(
    src: gaia.GaiaSource,
    *,
    mjd_a: float,
    mjd_b: float,
    wcs: Any,
    image_a: np.ndarray,
    image_b: np.ndarray,
    aperture_noise: float,
) -> tuple[float, dict[str, Any] | None]:
    """Shift (px) of a Gaia star between the epochs and, when it is static and its flux agrees
    in both epochs, the evidence that a residual on it is a PSF/wavelength systematic."""
    xa, ya = (float(v) for v in wcs.world_to_pixel_values(*src.position_at(mjd_a)))
    xb, yb = (float(v) for v in wcs.world_to_pixel_values(*src.position_at(mjd_b)))
    shift = math.hypot(xb - xa, yb - ya)
    if shift >= STATIC_MAX_SHIFT_PX:
        return shift, None
    ix, iy = int(round(xa)), int(round(ya))
    ny, nx = image_a.shape
    if not (0 <= ix < nx and 0 <= iy < ny):
        return shift, None
    flux_a, _ = aperture_photometry(image_a, ix, iy)
    flux_b, _ = aperture_photometry(image_b, ix, iy)
    if not (math.isfinite(flux_a) and math.isfinite(flux_b)) or flux_a <= 0 or flux_b <= 0:
        return shift, None  # Saturated, off the image or not detected: cannot vouch for it.
    brightest = max(flux_a, flux_b)
    if brightest < SYSTEMATIC_MIN_STAR_SNR * aperture_noise:
        return shift, None
    rel_change = abs(flux_b - flux_a) / brightest
    if rel_change > SYSTEMATIC_MAX_REL_CHANGE:
        return shift, None
    return shift, {
        "reason": "catalogued star, static and with consistent flux: likely PSF/wavelength systematic",
        "shift_px": round(shift, 3),
        "flux_ratio_b_over_a": round(flux_b / flux_a, 3),
    }


def classify_changes(
    detections: list[dict[str, Any]],
    gaia_sources: list[gaia.GaiaSource],
    wise_sources: list[wise.WiseSource],
    *,
    mjd_a: float,
    mjd_b: float,
    g_complete: float | None,
    match_radius_arcsec: float = config.PIXEL_SCALE_ARCSEC,
    search: ChangeSearch | None = None,
    wcs: Any = None,
) -> list[dict[str, Any]]:
    """Label each detected change.

    - ``catalogued_systematic``: on a Gaia star that does not move between the epochs and whose
      flux agrees within ``SYSTEMATIC_MAX_REL_CHANGE``: most likely a PSF/wavelength residual,
      not a change. Needs ``search`` (the normalised epochs) and ``wcs``.
    - ``catalogued_object``: a Gaia (epoch A or B) or CatWISE (epoch B) source within
      ``match_radius_arcsec``, or a residual within ``SYSTEMATIC_MATCH_RADIUS_PX`` of a Gaia star
      that moved between the epochs (one lobe of its motion dipole).
    - ``candidate_signal``: nothing catalogued explains it.
    """
    can_vouch = search is not None and wcs is not None
    aperture_noise = 0.0
    if can_vouch:
        aperture_noise = _robust_sigma(search.image_a) * (2 * APERTURE_RADIUS_PX + 1)
    wide_radius = max(match_radius_arcsec, SYSTEMATIC_MATCH_RADIUS_PX * config.PIXEL_SCALE_ARCSEC)

    out: list[dict[str, Any]] = []
    for det in detections:
        ra, dec = det["ra"], det["dec"]
        gaia_match = None
        systematic = None
        if gaia_sources:
            m_a = gaia.nearest(gaia_sources, ra, dec, mjd_a)
            m_b = gaia.nearest(gaia_sources, ra, dec, mjd_b)
            best_g = min(
                (m for m in (m_a, m_b) if m is not None),
                key=lambda m: m[1],
                default=None,
            )
            if best_g is not None:
                src, dist = best_g
                if dist <= match_radius_arcsec:
                    gaia_match = _gaia_payload(src, dist)
                if can_vouch and dist <= wide_radius:
                    shift, systematic = _systematic_check(
                        src,
                        mjd_a=mjd_a,
                        mjd_b=mjd_b,
                        wcs=wcs,
                        image_a=search.image_a,
                        image_b=search.image_b,
                        aperture_noise=aperture_noise,
                    )
                    if gaia_match is None and (systematic is not None or shift >= STATIC_MAX_SHIFT_PX):
                        gaia_match = _gaia_payload(src, dist)

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

        if systematic is not None:
            classification = "catalogued_systematic"
        elif gaia_match is not None or wise_match is not None:
            classification = "catalogued_object"
        else:
            classification = "candidate_signal"
        out.append(
            det
            | {
                "classification": classification,
                "gaia_match": gaia_match,
                "wise_match": wise_match,
                "systematic": systematic,
                "gaia_complete_to_g": g_complete,
            }
        )
    return out


def rank_changes(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Changes first (strongest first), likely systematics last, so a cap never hides a change."""
    return sorted(
        candidates,
        key=lambda c: (c["classification"] == "catalogued_systematic", -float(c["snr"])),
    )


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
