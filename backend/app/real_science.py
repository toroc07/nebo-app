"""The science bundle measured on a patch's own SPHEREx data, with no demonstration profile.

- Measured spectrum (P1-1): one point per exposure, the 3x3 aperture flux minus the local sky.
- 102-channel spectrum and 17 indices: the per-channel medians of that measured spectrum.
- Light curve: each visit's flux relative to the object's own spectrum (every exposure divided by
  the median of its channel), so the linear variable filter's wavelength sweep does not look like
  variability; scaled to the object's median SPHEREx flux.
- Model 1 features: the first-vs-last epoch difference around the object after flux scaling and
  PSF matching (as in /candidates), the ePSF fit of the first epoch, the flag fractions of the
  exposures, the Gaia DR3 / CatWISE cross-match and the B6/B2 colour of the spectrum.

A part that cannot be measured (a saturated star has no spectrum; fewer than three visits give no
light curve) is reported as unavailable with its reason. It is never filled with a profile: the
demonstration profiles of ``models`` are only used when a caller asks for a ``scenario``.
"""

from __future__ import annotations

import io
import math
from typing import Any, Callable

import numpy as np

from . import config, crossmatch, ephemeris, imaging, metrics, science_catalogs
from .store import Patch, Store

DATA_SOURCE = "NASA/IPAC IRSA SPHEREx spectral images"

# Model rows computed here are stored under this version, apart from the old simulated ones (v1).
MEASURED_VERSION = "v2-measured"
# A 102-channel spectrum needs at least this many measured channels to be classified.
MIN_SPECTRUM_CHANNELS = 20
# A channel is a reference for the light curve when its median is this significant and it has at
# least this many exposures (one exposure divided by itself would say nothing).
CHANNEL_MIN_SNR = 3.0
CHANNEL_MIN_POINTS = 3
# Exposures further apart than this belong to different visits.
VISIT_GAP_DAYS = 10.0
MIN_POINTS_PER_VISIT = 3
MIN_LIGHT_CURVE_VISITS = 3
# Visit-to-visit calibration repeatability, added in quadrature to each visit's error (1.5 %):
# flat field, filter and pointing differ between visits, so a change smaller than this is not
# claimed as variability (on Eps Indi B the visits scatter by ~2 % with 0.6 % noise errors).
VISIT_CALIBRATION_ERROR = 0.015
# Half side of the box around the object where the epoch difference is measured (21 x 21 px).
DIFF_HALF_BOX_PX = 10
# Share of a still star's brightness its epoch-to-epoch residual reaches through the filter's
# wavelength sweep (measured on Barnard's Star detector 3: per-star ratios 0.91-1.13, P1-5).
SYSTEMATIC_CHANGE_FRACTION = 0.15
# An "event" for Model 1: a dipole whose lobes both pass 3σ, or a brightness change at the object
# of at least this many σ (one aperture, so no look-elsewhere penalty).
EVENT_MIN_DIPOLE_Z = 3.0
EVENT_MIN_MONO_Z = 4.0
# Detectors tried for the epoch difference when the target recommends none.
DETECTOR_ORDER = (3, 2, 4, 1, 5, 6)
# The object counts as saturated on a detector when this share of its checked exposures is.
SATURATED_SHARE = 0.5

MEASURED_NOTE = (
    "Measured on this patch's SPHEREx data: the spectrum and the light curve come from its "
    "exposures, the Model 1 features from its epoch images, Gaia DR3 and CatWISE. Models 1-3 are "
    "hand-tuned estimates on those measurements, not detections."
)


MEASURED_SPECTRUM_NOTE = (
    "Measured: one point per SPHEREx exposure, a 3x3-pixel aperture at the object's position on "
    "that date (proper motion applied), minus the local sky level from an annulus 4-9 pixels "
    "around it; no aperture correction, so the flux is a lower bound of the total (roughly 70-90 "
    "%). Points where the light peaks on a neighbour (1.2 px or more from the object) are drawn "
    "apart and left out of the median. A neighbour closer than that cannot be told apart at "
    "6.15\" per pixel and stays in: for a faint object the short wavelengths may be its light "
    "(e.g. WISE 0855 is only its own source above ~4 µm). Exposures with saturated pixels near "
    "the object are left out (lower limits). Points come from all epochs, so a variable object "
    "scatters."
)

MEASURED_SPECTRUM_NOTE_RAW = (
    "Measured: one point per SPHEREx exposure, a 3x3-pixel aperture at the object's position on "
    "that date (proper motion applied), without aperture correction or local background "
    "subtraction (this field has not been processed for it yet). Reliable for bright sources; "
    "for faint ones the sky background dominates. Exposures with saturated pixels near the "
    "object are left out (their flux is only a lower limit). Points come from all epochs, so a "
    "variable object scatters."
)

# The light in the aperture peaking this far (pixels) from the object means a neighbour
# dominates it: a source on the object peaks within half a pixel diagonal (~0.7 px).
BLENDED_PEAK_OFFSET_PX = 1.2


def _finite(value: Any) -> bool:
    return value is not None and math.isfinite(float(value))


def measured_spectrum(exposures: list[dict]) -> dict:
    """The spectrum measured from the stored exposures (P1-1): every usable exposure as a point
    (wavelength, flux, sigma) and, per SPHEREx channel, the median flux with a robust error.

    Once the patch has local-background values (new builds, or ``app.backfill_background``),
    each flux has 9x the annulus sky level subtracted and rows without one are left out, so the
    curve never mixes subtracted and raw points. Points whose light peaks on a neighbour are
    marked ``blended`` and kept out of the per-channel median.
    """
    usable = [
        e for e in exposures
        if not e.get("saturated_near_target")
        and _finite(e.get("aperture_flux_ujy")) and _finite(e.get("wavelength_um"))
    ]
    subtract = any(_finite(e.get("local_background_mjy_sr")) for e in usable)
    scale = imaging.pixel_to_ujy()
    points, saturated, missing, no_background = [], 0, 0, 0
    for e in exposures:
        if e.get("saturated_near_target"):
            saturated += 1
            continue
        flux, lam = e.get("aperture_flux_ujy"), e.get("wavelength_um")
        if not (_finite(flux) and _finite(lam)):
            missing += 1
            continue
        sigma = e.get("aperture_sigma_reported_ujy") or e.get("aperture_sigma_stat_ujy")
        sigma = float(sigma) if _finite(sigma) else None
        background_ujy = None
        if subtract:
            if not _finite(e.get("local_background_mjy_sr")):
                no_background += 1
                continue
            background_ujy = 9 * float(e["local_background_mjy_sr"]) * scale
            flux = float(flux) - background_ujy
            if sigma is not None and _finite(e.get("local_background_sigma_mjy_sr")):
                sigma = math.hypot(sigma, 9 * float(e["local_background_sigma_mjy_sr"]) * scale)
        offset = e.get("aperture_peak_offset_px")
        points.append({
            "wavelength_um": round(float(lam), 5),
            "flux_ujy": float(flux),
            "sigma_ujy": sigma,
            "background_ujy": background_ujy,
            "blended": _finite(offset) and float(offset) >= BLENDED_PEAK_OFFSET_PX,
            "detector": e.get("detector"),
            "channel_id": e.get("channel_id"),
            "epoch_index": e.get("epoch_index"),
            "mjd": e.get("mid_mjd"),
        })
    points.sort(key=lambda p: p["wavelength_um"])
    by_channel: dict[int, list[dict]] = {}
    for p in points:
        if p["channel_id"] is not None and not p["blended"]:
            by_channel.setdefault(int(p["channel_id"]), []).append(p)
    channels = []
    for channel_id, group in sorted(by_channel.items()):
        fluxes = np.array([p["flux_ujy"] for p in group])
        median = float(np.median(fluxes))
        # Robust error of the median: 1.4826·MAD/√n; a single point keeps its own sigma.
        if len(group) > 1:
            sigma = float(1.4826 * np.median(np.abs(fluxes - median)) / math.sqrt(len(group)))
        else:
            sigma = group[0]["sigma_ujy"]
        channels.append({
            "channel_id": channel_id,
            "wavelength_um": round(float(np.median([p["wavelength_um"] for p in group])), 5),
            "flux_ujy": median,
            "sigma_ujy": sigma,
            "n": len(group),
        })
    return {
        "measured": True,
        "source": DATA_SOURCE,
        "unit": "uJy",
        "background_subtracted": subtract,
        "note": MEASURED_SPECTRUM_NOTE if subtract else MEASURED_SPECTRUM_NOTE_RAW,
        "points": points,
        "channels": channels,
        "blended_points": sum(1 for p in points if p["blended"]),
        "excluded_saturated": saturated,
        "excluded_missing": missing,
        "excluded_no_background": no_background,
    }


# ----- 102-channel spectrum and light curve from the measured spectrum -------------------------


def spectrum_102(measured: dict) -> tuple[dict | None, str | None]:
    """The 102-channel spectrum (mJy) from the measured per-channel medians, or the reason why not."""
    by_id = {int(c["channel_id"]): c for c in measured["channels"]}
    flux: list[float | None] = []
    variance: list[float | None] = []
    sigma: list[float | None] = []
    valid: list[bool] = []
    hits: list[int] = []
    for ch in science_catalogs.SPHEREX_102_CHANNELS:
        c = by_id.get(ch.channel_id)
        stat = c.get("sigma_ujy") if c else None
        if ch.is_blankch or not c or not stat or not math.isfinite(stat) or stat <= 0:
            flux.append(None)
            variance.append(None)
            sigma.append(None)
            valid.append(False)
            hits.append(int(c["n"]) if c and not ch.is_blankch else 0)
            continue
        f, s = c["flux_ujy"] / 1000.0, stat / 1000.0
        flux.append(round(f, 6))
        variance.append(round(s * s, 12))
        sigma.append(round(science_catalogs.compute_reported_sigma(f, s), 6))
        valid.append(True)
        hits.append(int(c["n"]))
    n_valid = sum(valid)
    if n_valid < MIN_SPECTRUM_CHANNELS:
        if measured["excluded_saturated"] and len(measured["points"]) < MIN_SPECTRUM_CHANNELS:
            return None, (
                f"The object saturates SPHEREx near its position ({measured['excluded_saturated']} "
                "exposures): their flux is only a lower limit, so no spectrum can be measured."
            )
        return None, (
            f"Only {n_valid} SPHEREx channels have a clean measurement of the object "
            f"(at least {MIN_SPECTRUM_CHANNELS} are needed to classify a spectrum)."
        )
    return {
        "spectrum_scope": "all_epochs",
        "data_source": "measured",
        "wavelengths_um": [ch.lambda_c_um for ch in science_catalogs.SPHEREX_102_CHANNELS],
        "flux_mjy": flux,
        "variance_mjy2": variance,
        "sigma_reported_mjy": sigma,
        "valid_mask": valid,
        "channel_hit_counts": hits,
        "valid_channel_count": n_valid,
        "band_coadd_flux_mjy": metrics.compute_band_coadds(flux, sigma, valid),
        "background_subtracted": measured["background_subtracted"],
    }, None


def light_curve(measured: dict) -> tuple[dict | None, str | None]:
    """Flux per visit relative to the object's own spectrum, in mJy, or the reason why not.

    Every exposure is modelled as the object's flux in its channel times its visit's factor, and
    both are fitted together (alternating medians). Dividing by a plain channel median would
    include the exposure itself and pull every visit towards 1; leaving the visit out biases the
    factors when there are only a few visits.
    """
    significant = {
        int(c["channel_id"]): float(c["flux_ujy"])
        for c in measured["channels"]
        if c.get("sigma_ujy")
        and c["n"] >= CHANNEL_MIN_POINTS
        and c["flux_ujy"] > CHANNEL_MIN_SNR * c["sigma_ujy"]
    }
    if not significant:
        return None, (
            "No channel of the object is detected at 3σ in several exposures, so there is no "
            "flux to follow over time."
        )
    points = sorted(
        (
            p for p in measured["points"]
            if not p["blended"] and p.get("mjd") is not None and p.get("channel_id") in significant
        ),
        key=lambda p: p["mjd"],
    )
    visits: list[list[dict]] = []
    for p in points:
        if not visits or p["mjd"] - visits[-1][-1]["mjd"] > VISIT_GAP_DAYS:
            visits.append([])
        visits[-1].append(p)
    # Each exposure = (the object's flux in that channel) x (that visit's factor): a least-squares
    # fit in log space by alternating means, with 4σ clipping. Medians would be degenerate here
    # (one exposure per channel and visit makes many ratios exactly 1); only channels seen in at
    # least two visits constrain the factors.
    seen: dict[int, set[int]] = {}
    for v, visit in enumerate(visits):
        for p in visit:
            seen.setdefault(p["channel_id"], set()).add(v)
    rows = [
        (v, p["channel_id"], math.log(p["flux_ujy"]), p)
        for v, visit in enumerate(visits) for p in visit
        if len(seen[p["channel_id"]]) >= 2 and p["flux_ujy"] > 0
    ]
    keep = [True] * len(rows)
    log_factor = {v: 0.0 for v in range(len(visits))}
    log_sed: dict[int, float] = {}
    for _clip in range(3):
        for _ in range(30):
            sums: dict[int, list[float]] = {}
            for ok, (v, c, y, _p) in zip(keep, rows):
                if ok:
                    sums.setdefault(c, []).append(y - log_factor[v])
            log_sed = {c: float(np.mean(values)) for c, values in sums.items()}
            per_visit: dict[int, list[float]] = {}
            for ok, (v, c, y, _p) in zip(keep, rows):
                if ok and c in log_sed:
                    per_visit.setdefault(v, []).append(y - log_sed[c])
            new = {v: float(np.mean(values)) for v, values in per_visit.items()}
            shift = float(np.median(list(new.values()))) if new else 0.0
            log_factor = {v: new.get(v, shift) - shift for v in log_factor}
        residual = np.array([y - log_sed.get(c, y) - log_factor[v] for v, c, y, _p in rows])
        mad = 1.4826 * float(np.median(np.abs(residual[np.array(keep)]))) if any(keep) else 0.0
        if mad <= 0:
            break
        keep = [bool(abs(r) <= 4 * mad) for r in residual]

    reference_mjy = float(np.median(list(significant.values()))) / 1000.0
    times, fluxes, sigmas, counts = [], [], [], []
    for v, visit in enumerate(visits):
        used = [(p, r) for ok, (vv, _c, _y, p), r in zip(keep, rows, residual) if ok and vv == v]
        if len(used) < MIN_POINTS_PER_VISIT:
            continue
        median = math.exp(log_factor[v])
        # Relative error of the visit factor: scatter of its exposures about the fit, and their
        # own photometric errors, each over sqrt(n).
        ratios = np.array([r for _p, r in used])
        scatter = float(np.std(ratios, ddof=1)) / math.sqrt(ratios.size) if ratios.size > 1 else 0.0
        photometric = [p["sigma_ujy"] / p["flux_ujy"] for p, _r in used if p.get("sigma_ujy")]
        noise = float(np.median(photometric)) / math.sqrt(ratios.size) if photometric else 0.0
        pairs = used
        error = math.hypot(max(scatter, noise), VISIT_CALIBRATION_ERROR)
        times.append(round(float(np.median([p["mjd"] for p, _ in pairs])), 4))
        fluxes.append(round(median * reference_mjy, 6))
        sigmas.append(round(error * reference_mjy, 6))
        counts.append(len(pairs))
    if len(times) < MIN_LIGHT_CURVE_VISITS:
        return None, (
            f"{len(times)} visit{'' if len(times) == 1 else 's'} with enough clean exposures of "
            f"the object; a light curve needs at least {MIN_LIGHT_CURVE_VISITS}."
        )
    return {
        "times_mjd": times,
        "fluxes_mjy": fluxes,
        "sigmas_mjy": sigmas,
        "exposures_per_visit": counts,
        "reference_mjy": round(reference_mjy, 6),
        "method": (
            "Each exposure = the object's flux in its channel x its visit's factor, fitted "
            "together; the factors times the object's median SPHEREx flux. The wavelength sweep "
            "of the filter cancels."
        ),
    }, None


# ----- Model 1 features from the epoch images --------------------------------------------------


def _object_pixel(patch: Patch, target: dict | None, mjd: float, wcs: Any) -> tuple[float, float]:
    """The object's pixel on the float-data grid (FITS orientation) at ``mjd``."""
    ra, dec = patch.ra, patch.dec
    if target and target.get("pm_ra_mas_yr") is not None and target.get("pm_dec_mas_yr") is not None:
        ra, dec = ephemeris.expected_position(
            patch.ra, patch.dec, target["pm_ra_mas_yr"], target["pm_dec_mas_yr"], mjd
        )
    x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
    return x, y


def _epoch_pair(store: Store, patch: Patch, target: dict | None):
    """(detector, (image, data, variance) of the first and of the last epoch) with float data."""
    recommended = (target or {}).get("recommended_detector")
    order = [int(recommended)] if recommended else []
    order += [d for d in DETECTOR_ORDER if d not in order]
    largest = max(config.SIZES_DEG, key=lambda name: config.SIZES_DEG[name])
    for detector in order:
        timeline = store.get_timeline(patch.id, detector)
        if timeline is None or timeline.status != "ready":
            continue
        images = sorted(
            (i for i in store.list_images(timeline.id, largest) if i.has_npz),
            key=lambda i: i.epoch_index,
        )
        if len(images) < 2:
            continue
        loaded = []
        for image in images:
            npz = store.get_npz(image.id)
            if npz is not None:
                data = np.load(io.BytesIO(npz))
                loaded.append(
                    (image, data["image"].astype(np.float64), data["variance"].astype(np.float64))
                )
        if len(loaded) >= 2:
            return detector, loaded
    return None


# The PSF features of Model 1 were set on idealised profiles (a point source scores ~these values).
# On real co-adds a Gaussian fit is never ideal (undersampled, wavelength-dependent PSF) and its
# chi-square grows with brightness, so the object is measured against the field's own stars and
# mapped onto that point-source scale: shaped like the field's stars, it scores the reference.
# q_fit_epsf and chi2_psf come from the moment width (brightness-independent): w = width/field
# width, q = w and chi2 = 1.05·w²; c_80_20 and bg_gradient_norm are plain ratios to the field.
POINT_SOURCE_REFERENCE = {"q_fit_epsf": 1.0, "chi2_psf": 1.05, "c_80_20": 2.05, "bg_gradient_norm": 0.012}
RATIO_FEATURES = ("c_80_20", "bg_gradient_norm")
FIELD_STAR_MIN_SNR = 20.0
FIELD_STAR_MAX = 15
FIELD_STAR_MIN = 3
# Field stars this close to the object (pixels) are skipped, so the object never sets its own scale.
FIELD_STAR_EXCLUSION_PX = 8.0


def _field_star_shapes(image: np.ndarray, variance: np.ndarray, x: float, y: float) -> dict | None:
    """Median PSF-fit features of the field's bright, unblended stars (None with fewer than 3)."""
    centred = image - float(np.nanmedian(image))
    noise = crossmatch._robust_sigma(centred)
    stars = [
        (sx, sy)
        for _, sx, sy in crossmatch._local_maxima(centred, FIELD_STAR_MIN_SNR * noise, edge=6)
        if math.hypot(sx - x, sy - y) > FIELD_STAR_EXCLUSION_PX
    ][:FIELD_STAR_MAX]
    if len(stars) < FIELD_STAR_MIN:
        return None
    rows = [metrics.extract_optimal_psf_photometry(image, variance, center_xy=s) for s in stars]
    widths = [crossmatch.aperture_photometry(image, sx, sy)[1] for sx, sy in stars]
    out: dict[str, float] = {}
    for name, values in (
        *((n, [float(r[n]) for r in rows]) for n in RATIO_FEATURES),
        ("width_px", [float(w) for w in widths]),
    ):
        good = [v for v in values if math.isfinite(v) and v > 0]
        if len(good) < FIELD_STAR_MIN:
            return None
        out[name] = float(np.median(good))
    out["n_stars"] = len(stars)
    return out


# Centroid shift used as motion evidence: at least this far (px), and each epoch's centroid is
# never known better than this (undersampled PSF, wavelength-dependent centroid).
MIN_CENTROID_SHIFT_PX = 0.4
CENTROID_FLOOR_PX = 0.1
# A saturated core is centred on its wings only: its centroid is known no better than this.
CENTROID_FLOOR_SATURATED_PX = 0.2
# Gaussian sigma of a SPHEREx point source on the co-add grid (px), for the centroid error.
PSF_SIGMA_PX = 0.7


def _astrometric_motion(epochs: list[tuple[float, np.ndarray, tuple[float, float]]], saturated: bool) -> dict | None:
    """The object's centroid shift between the first and last epochs where it is detected, and
    its significance (the P1-6 centroids, fitted near the object's expected pixel in each epoch).

    A centroid's error is the PSF width over the detection S/N, floored. Symmetry is how well the
    flux is conserved (a source that moved, rather than one that appeared, faded or brightened).
    """
    from .position_report import measure_centroid

    found = []
    for _, data, (x, y) in epochs:
        image = data - float(np.nanmedian(data))
        centroid = measure_centroid(image, None, x, y)
        if centroid is not None:
            found.append((image, centroid))
    if len(found) < 2:
        return None
    (image_a, ca), (image_b, cb) = found[0], found[-1]
    shift = math.hypot(cb.x - ca.x, cb.y - ca.y)
    if shift < MIN_CENTROID_SHIFT_PX:
        return {"z": 0.0, "symmetry": 0.0, "shift_arcsec": 0.0, "shift_px": round(shift, 3)}
    floor = CENTROID_FLOOR_SATURATED_PX if saturated else CENTROID_FLOOR_PX
    sigma = math.hypot(max(floor, PSF_SIGMA_PX / ca.snr), max(floor, PSF_SIGMA_PX / cb.snr))
    fa = crossmatch.aperture_photometry(image_a, round(ca.x), round(ca.y))[0]
    fb = crossmatch.aperture_photometry(image_b, round(cb.x), round(cb.y))[0]
    symmetry = (
        1.0 - abs(fa - fb) / (abs(fa) + abs(fb))
        if math.isfinite(fa) and math.isfinite(fb) and abs(fa) + abs(fb) > 0
        else 0.5
    )
    return {
        "z": round(shift / sigma, 4),
        "symmetry": round(max(0.0, min(1.0, symmetry)), 4),
        "shift_arcsec": round(shift * config.PIXEL_SCALE_ARCSEC, 4),
        "shift_px": round(shift, 3),
    }


def _mean(values: list[Any]) -> float | None:
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.mean(finite)) if finite else None


def model1_features(
    store: Store,
    patch: Patch,
    target: dict | None,
    exposures: list[dict],
    spectrum: dict | None,
    gaia_info: dict | None,
    wise_info: dict | None,
) -> tuple[dict | None, dict]:
    """The Model 1 features measured on this patch, and how (detector, epochs, what is missing).

    A feature that cannot be measured is left out: the model then uses its neutral reference
    value, which adds nothing to any class.
    """
    pair = _epoch_pair(store, patch, target)
    if pair is None:
        return None, {
            "reason": "No detector has two finished epochs with float data yet, so there is no "
            "change to measure."
        }
    detector, epochs = pair
    (img_a, a, var_a), (img_b, b, var_b) = epochs[0], epochs[-1]
    largest = max(config.SIZES_DEG, key=lambda name: config.SIZES_DEG[name])
    wcs, _ = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[largest])
    search = crossmatch.find_epoch_changes(a, b, wcs, normalise=True)
    if search is None:
        return None, {"reason": "The first and last epochs do not overlap, so they cannot be compared."}
    scale = search.normalisation.flux_scale
    xa, ya = _object_pixel(patch, target, img_a.mid_mjd, wcs)
    xb, yb = _object_pixel(patch, target, img_b.mid_mjd, wcs)
    cx, cy = round((xa + xb) / 2), round((ya + yb) / 2)
    h = DIFF_HALF_BOX_PX
    box = (slice(max(0, cy - h), cy + h + 1), slice(max(0, cx - h), cx + h + 1))
    # The difference as /candidates sees it (flux-scaled, PSF-matched, smoothed), judged against
    # its empirical noise plus a systematic floor proportional to the local brightness: a still
    # star changes by 10-20 % between epochs through the filter's wavelength sweep, so only a
    # residual well above that (a source that moved, appeared or varied) is significant.
    norm = search.normalisation

    def matched(image: np.ndarray, epoch: str) -> np.ndarray:
        if norm.psf_matched_epoch == epoch:
            image = crossmatch.gaussian_smooth(image, norm.psf_match_kernel_px)
        return crossmatch.gaussian_smooth(image, norm.smoothing_sigma_px)

    a_cmp, b_cmp = matched(search.image_a, "a")[box], matched(search.image_b, "b")[box]
    floor = SYSTEMATIC_CHANGE_FRACTION * np.abs(0.5 * (a_cmp + b_cmp))
    half_var = (norm.noise_sigma**2 + floor**2) / 2.0
    diff = metrics.compute_difference_snr_map(a_cmp, half_var, b_cmp, half_var)
    phot = metrics.extract_optimal_psf_photometry(a, var_a, center_xy=(xa, ya))

    on_detector = [e for e in exposures if e.get("detector") == detector]
    checked = [
        bool(e["saturated_near_target"]) for e in on_detector
        if e.get("saturated_near_target") is not None
    ]
    saturated = bool(checked) and sum(checked) / len(checked) >= SATURATED_SHARE
    dipole = diff["z_dipole"] > 0  # both lobes beyond 3σ
    motion = {
        "z": diff["z_dipole"],
        # Without a significant dipole the "shift" between the box's extreme pixels is noise.
        "symmetry": diff["dipole_symmetry"] if dipole else 0.0,
        "shift_arcsec": diff["angular_shift_arcsec"] if dipole else 0.0,
        "from": "difference_dipole" if dipole else None,
    }
    astrometry = _astrometric_motion(
        [(img.mid_mjd, data, _object_pixel(patch, target, img.mid_mjd, wcs)) for img, data, _ in epochs],
        saturated,
    )
    if astrometry and astrometry["z"] >= EVENT_MIN_DIPOLE_Z and astrometry["z"] > motion["z"]:
        # A faint or blended mover may not leave a dipole above the systematic floor, but its
        # centroid still moves: the same physical evidence, measured more sensitively.
        motion = astrometry | {"from": "centroid_shift"}
    fv: dict[str, float] = {
        "z_mono": diff["z_mono"],
        "z_dipole": motion["z"],
        "dipole_symmetry": motion["symmetry"],
        "angular_shift_arcsec": motion["shift_arcsec"],
        "is_he_1083_channel": 0.0,
        "bg_gradient_ratio": phot["bg_gradient_ratio"],
    }
    unavailable: list[str] = []
    field = _field_star_shapes(a, var_a, xa, ya)
    width = crossmatch.aperture_photometry(a, round(xa), round(ya))[1]
    if saturated or field is None or not math.isfinite(width) or width <= 0:
        # A clipped core has no PSF shape: the fit-quality features stay neutral.
        unavailable += ["q_fit_epsf", "chi2_psf", "c_80_20"]
    else:
        w = width / field["width_px"]
        fv["q_fit_epsf"] = POINT_SOURCE_REFERENCE["q_fit_epsf"] * w
        fv["chi2_psf"] = POINT_SOURCE_REFERENCE["chi2_psf"] * w * w
        fv["c_80_20"] = POINT_SOURCE_REFERENCE["c_80_20"] * float(phot["c_80_20"]) / field["c_80_20"]
    gradient = float(phot["bg_gradient_norm"])
    if field is None or not math.isfinite(gradient):
        unavailable.append("bg_gradient_norm")
    else:
        fv["bg_gradient_norm"] = POINT_SOURCE_REFERENCE["bg_gradient_norm"] * gradient / field["bg_gradient_norm"]
    clean = _mean([e.get("clean_pixel_fraction") for e in on_detector])
    flagged = _mean([e.get("science_bad_fraction") for e in on_detector])
    for name, value in (("p_clean_flags", clean), ("f_artifact_flags", flagged)):
        if value is None:
            unavailable.append(name)
        else:
            fv[name] = value
    add_catalogue_features(fv, unavailable, gaia_info, wise_info)
    bands = (spectrum or {}).get("band_coadd_flux_mjy") or {}
    b6 = (bands.get("band_6") or {}).get("flux_mjy")
    b2 = (bands.get("band_2") or {}).get("flux_mjy")
    if b6 is not None and b2 is not None and abs(b6) + abs(b2) > 0:
        fv["thermal_nsdi_b6_b2"] = (b6 - b2) / (abs(b6) + abs(b2))
    else:
        unavailable.append("thermal_nsdi_b6_b2")
    fv = {k: round(float(v), 6) for k, v in fv.items()}
    return fv, {
        "detector": detector,
        "epoch_a": img_a.epoch_index,
        "epoch_b": img_b.epoch_index,
        "mjd_a": img_a.mid_mjd,
        "mjd_b": img_b.mid_mjd,
        "flux_scale": round(scale, 4),
        "saturated": saturated,
        "z_pos_max": diff["z_pos_max"],
        "z_neg_min": diff["z_neg_min"],
        "motion_from": motion["from"],
        "centroid_shift_px": astrometry["shift_px"] if astrometry else None,
        "centroid_shift_z": astrometry["z"] if astrometry else None,
        "field_stars": field["n_stars"] if field else 0,
        "features_unavailable": unavailable,
    }


CATALOGUE_FEATURES = ("gaia_match_dist_arcsec", "gaia_pm_total_mas_yr", "wise_w1_w2_color")


def add_catalogue_features(
    fv: dict, unavailable: list[str], gaia_info: dict | None, wise_info: dict | None
) -> None:
    """Fill the Gaia DR3 / CatWISE features in place; missing ones are listed in ``unavailable``
    (and left out, so the model uses its neutral value)."""
    unavailable[:] = [name for name in unavailable if name not in CATALOGUE_FEATURES]
    if gaia_info and gaia_info.get("dist_arcsec") is not None:
        fv["gaia_match_dist_arcsec"] = round(float(gaia_info["dist_arcsec"]), 6)
        fv["gaia_pm_total_mas_yr"] = round(float(gaia_info.get("pm_total_mas_yr") or 0.0), 6)
    else:
        unavailable += ["gaia_match_dist_arcsec", "gaia_pm_total_mas_yr"]
    if wise_info and wise_info.get("w1_w2_color") is not None:
        fv["wise_w1_w2_color"] = round(float(wise_info["w1_w2_color"]), 6)
    else:
        unavailable.append("wise_w1_w2_color")


# Model 2's templates are idealised shapes; a reduced chi-square above this means none of them
# describes the measured spectrum, so its class is the least-bad template, not an identification.
MODEL2_GOOD_FIT_CHI2R = 5.0


def fit_quality(chi2_reduced: Any) -> dict:
    """How well Model 2's best template matches the measured spectrum, in plain words."""
    try:
        chi2r = float(chi2_reduced)
    except (TypeError, ValueError):
        chi2r = float("nan")
    if math.isfinite(chi2r) and chi2r <= MODEL2_GOOD_FIT_CHI2R:
        return {"fit_quality": "good", "fit_note": f"The best template matches the spectrum (χ²ᵣ = {chi2r:.1f})."}
    shown = f"{chi2r:.0f}" if math.isfinite(chi2r) else "n/a"
    return {
        "fit_quality": "poor",
        "fit_note": (
            f"No template matches this measured spectrum (χ²ᵣ = {shown}): the class is only the "
            "least-bad template, not an identification."
        ),
    }


def confidence(fv: dict, info: dict) -> dict:
    """Global confidence score (Section 4.3) from the measured features."""
    flags = ["OVERFLOW"] if info.get("saturated") else []
    if fv.get("f_artifact_flags", 0.0) > 0.3:
        flags.append("SNOWBALL")
    return metrics.compute_global_confidence_score(
        snr=max(fv["z_mono"], fv["z_dipole"]),
        dipole_symmetry=fv["dipole_symmetry"],
        angular_shift_px=fv["angular_shift_arcsec"] / config.PIXEL_SCALE_ARCSEC,
        active_flag_names=flags,
        q_fit_epsf=fv.get("q_fit_epsf", 1.0),
        is_stationary=fv["z_dipole"] < 3.0,
    )


# ----- the whole bundle --------------------------------------------------------------------------


def analyze(
    store: Store,
    patch: Patch,
    *,
    force_recompute: bool = False,
    gaia_info: dict | None = None,
    wise_info: dict | None = None,
    crossmatch: Callable[[], tuple[dict | None, dict | None]] | None = None,
) -> dict[str, Any]:
    """Spectrum, 17 indices, light curve, variability, confidence and Models 1-3, all measured.

    Model results are stored under ``MEASURED_VERSION`` and reused while ``force_recompute`` is
    false; the spectrum and the light curve are recomputed from the stored exposures each time
    (one query, no image). ``crossmatch`` returns the Gaia/CatWISE match on demand: it is only
    called when Model 1 has an event to classify (given ``gaia_info``/``wise_info`` win).
    """
    from . import models  # models imports this module lazily too

    target = store.get_target(patch.target_slug) if patch.target_slug else None
    exposures = store.list_nasa_sector_exposures(patch.id)
    measured = measured_spectrum(exposures)
    spectrum, spectrum_reason = spectrum_102(measured)
    indices = metrics.compute_all_17_spectral_indices(spectrum) if spectrum else []
    if spectrum is not None:
        spectrum["indices"] = indices
    curve, curve_reason = light_curve(measured)
    variability = (
        metrics.compute_variability_metrics(curve["times_mjd"], curve["fluxes_mjy"], curve["sigmas_mjy"])
        if curve
        else None
    )
    unavailable: dict[str, str] = {}
    if spectrum_reason:
        unavailable["spectrum"] = unavailable["model2_spectrum"] = spectrum_reason
    if curve_reason:
        unavailable["light_curve"] = unavailable["model3_forecast"] = curve_reason

    m1 = None if force_recompute else store.get_model1_attribution(patch.id, -1, MEASURED_VERSION)
    conf = None
    if m1 is not None:
        measurement = (m1.get("researcher_level2") or {}).get("measurement") or {}
        conf = confidence(m1["feature_vector"], measurement)
    else:
        fv, info = model1_features(store, patch, target, exposures, spectrum, gaia_info, wise_info)
        if fv is None:
            unavailable["model1_event"] = unavailable["confidence"] = info["reason"]
        else:
            conf = confidence(fv, info)
            moved = fv["z_dipole"] >= EVENT_MIN_DIPOLE_Z
            if info["saturated"] and not moved:
                # A clipped core's brightness change is not measurable; only motion is.
                unavailable["model1_event"] = (
                    f"The object saturates SPHEREx on detector {info['detector']}, so a change in its "
                    "brightness cannot be measured, and it shows no significant motion: there is "
                    "no event to classify."
                )
            elif not moved and abs(fv["z_mono"]) < EVENT_MIN_MONO_Z:
                # Model 1 classifies an event; with no significant change there is none.
                unavailable["model1_event"] = (
                    f"No significant change at the object's position between epochs "
                    f"{info['epoch_a'] + 1} and {info['epoch_b'] + 1} on detector {info['detector']} "
                    f"(change {fv['z_mono']:+.1f}σ, no dipole above 3σ): there is no event to classify."
                )
            else:
                # The catalogue cross-match is a network query (slow, and often down): asked only
                # now that there is an event to classify, never for a field without one.
                if crossmatch is not None and gaia_info is None and wise_info is None:
                    gaia_info, wise_info = crossmatch()
                    add_catalogue_features(fv, info["features_unavailable"], gaia_info, wise_info)
                payload = models.run_model1_event_classifier(fv, model_version=MEASURED_VERSION)
                payload["researcher_level2"] = dict(payload.get("researcher_level2") or {}) | {
                    "measurement": info
                }
                m1 = store.save_model1_attribution(patch.id, -1, payload)

    m2 = None
    if spectrum is not None:
        m2 = None if force_recompute else store.get_model2_classification(patch.id, MEASURED_VERSION)
        if m2 is None:
            payload = models.run_model2_spectral_classifier(
                spectrum, indices=indices, model_version=MEASURED_VERSION
            )
            payload["citizen_level1"] = dict(payload.get("citizen_level1") or {}) | fit_quality(
                payload.get("chi2_reduced")
            )
            m2 = store.save_model2_classification(patch.id, payload)

    m3 = None
    if curve is not None:
        m3 = None if force_recompute else store.get_model3_forecast(patch.id, MEASURED_VERSION)
        if m3 is None:
            payload = models.run_model3_temporal_forecast(
                curve["times_mjd"],
                curve["fluxes_mjy"],
                curve["sigmas_mjy"],
                ra_deg=patch.ra,
                dec_deg=patch.dec,
                pm_ra_mas_yr=float((target or {}).get("pm_ra_mas_yr") or 0.0),
                pm_dec_mas_yr=float((target or {}).get("pm_dec_mas_yr") or 0.0),
                period_days=None,
                model1_result=m1,
                model1_attribution_id=m1["id"] if m1 else None,
                model_version=MEASURED_VERSION,
            )
            payload["researcher_level2"] = dict(payload.get("researcher_level2") or {}) | {
                "light_curve": curve
            }
            m3 = store.save_model3_forecast(patch.id, payload)

    return {
        "patch": {"id": patch.id, "ra": patch.ra, "dec": patch.dec, "target": patch.target_slug},
        "simulated": False,
        "data_note": MEASURED_NOTE,
        "confidence": conf,
        "variability": variability,
        "light_curve": curve,
        "spectrum": spectrum,
        "model1_event": m1,
        "model2_spectrum": m2,
        "model3_forecast": m3,
        "unavailable": unavailable,
    }

