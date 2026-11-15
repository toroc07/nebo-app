"""Change detection on synthetic epochs: flux scale, PSF homogenisation and systematic labels."""

import math

import numpy as np
import pytest

from app import config, crossmatch, gaia, imaging

RA, DEC = 270.446223, 4.76878
SIZE = "medium"
MJD_A = gaia.REF_EPOCH_MJD  # Gaia positions are given at epoch A, so A needs no propagation.
MJD_B = gaia.REF_EPOCH_MJD + 365.25
NOISE = 0.01

# (x, y, peak) in FITS pixels on the 59 px medium grid. Integer centres, like stars that the
# nearest-neighbour co-add puts on the same pixel phase in both epochs.
STARS = [
    (8, 9, 40.0), (20, 12, 12.0), (35, 7, 25.0), (50, 10, 6.0), (11, 25, 18.0),
    (27, 22, 9.0), (46, 26, 30.0), (9, 44, 7.0), (22, 38, 15.0), (39, 41, 22.0),
    (52, 47, 10.0), (16, 53, 28.0), (33, 52, 5.0), (47, 36, 14.0), (30, 31, 20.0),
]


def grid():
    wcs, (side, _) = imaging.make_target_grid(RA, DEC, config.SIZES_DEG[SIZE])
    return wcs, side


def render(side, stars, sigma_px=0.65, seed=0, background=0.2):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:side, 0:side]
    image = np.full((side, side), background) + rng.normal(0.0, NOISE, (side, side))
    for x, y, peak in stars:
        image += peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_px**2))
    return image.astype(np.float32)


def gaia_for(wcs, stars, mover=None):
    """Gaia sources at the stars' positions (static), plus an optional fast mover."""
    sources = []
    for i, (x, y, _) in enumerate(stars):
        ra, dec = (float(v) for v in wcs.pixel_to_world_values(x, y))
        sources.append(gaia.GaiaSource(f"s{i}", ra % 360.0, dec, 1.0, 1.0, 2.0, 14.0, 1.0))
    if mover is not None:
        (x, y), pm_dec = mover
        ra, dec = (float(v) for v in wcs.pixel_to_world_values(x, y))
        sources.append(gaia.GaiaSource("mover", ra % 360.0, dec, 0.0, pm_dec, 500.0, 9.0, 2.5))
    return sources


def near(detections, x, y_fits, side, radius=2.5):
    """Detections within ``radius`` px of a FITS position (detections carry PNG y)."""
    return [d for d in detections if math.hypot(d["x"] - x, d["y"] - (side - 1 - y_fits)) <= radius]


def test_static_field_with_a_flux_scale_offset_has_no_changes_after_normalisation():
    wcs, side = grid()
    a = render(side, STARS, seed=1)
    # Epoch B: the same sky, 20 % brighter (calibration/scale drift) on another background.
    b = render(side, [(x, y, 1.2 * p) for x, y, p in STARS], seed=2, background=0.35)

    raw = crossmatch.find_epoch_changes(a, b, wcs, normalise=False)
    assert len(raw.detections) >= 10  # Without scaling every bright star looks "changed".

    search = crossmatch.find_epoch_changes(a, b, wcs)
    assert search.detections == []
    norm = search.normalisation
    assert norm.flux_scale == pytest.approx(1 / 1.2, rel=0.02)
    assert norm.scale_stars >= crossmatch.MIN_SCALE_STARS
    assert norm.smoothing_sigma_px == crossmatch.HOMOGENISE_SIGMA_PX


def test_psf_matching_blurs_the_sharper_epoch_and_shrinks_star_residuals():
    wcs, side = grid()
    a = render(side, STARS, sigma_px=0.6, seed=3)
    # Same total flux, broader PSF in epoch B (peak scaled down to conserve flux).
    b = render(side, [(x, y, p * (0.6 / 0.8) ** 2) for x, y, p in STARS], sigma_px=0.8, seed=4)
    stars = [(x, y) for x, y, _ in STARS]
    kernel, epoch = crossmatch._psf_match_kernel(a, b, stars)
    assert epoch == "a" and 0.35 <= kernel <= 0.75  # sqrt(0.8^2 - 0.6^2) = 0.53 px

    def star_residual(first, second):
        return sum(float(np.sum((second[y - 3 : y + 4, x - 3 : x + 4] - first[y - 3 : y + 4, x - 3 : x + 4]) ** 2)) for x, y in stars)

    assert star_residual(crossmatch.gaussian_smooth(a, kernel), b) < 0.1 * star_residual(a, b)
    search = crossmatch.find_epoch_changes(a, b, wcs)
    assert search.normalisation.psf_matched_epoch == "a"
    assert search.normalisation.psf_sigma_b_px > search.normalisation.psf_sigma_a_px


def test_a_moved_star_is_detected_and_attributed_to_the_catalogued_mover():
    wcs, side = grid()
    mover_a, mover_b = (29, 29), (29, 31)  # 2 px north in one year: 12.3"/yr.
    a = render(side, STARS + [(*mover_a, 30.0)], seed=5)
    b = render(side, [(x, y, 1.1 * p) for x, y, p in STARS] + [(*mover_b, 33.0)], seed=6)

    search = crossmatch.find_epoch_changes(a, b, wcs)
    assert search.normalisation.flux_scale == pytest.approx(1 / 1.1, rel=0.03)
    on_mover = near(search.detections, 29, 30, side, radius=3.0)
    assert on_mover, "the moving star must be detected"
    assert {d["polarity"] for d in on_mover} == {"positive", "negative"} or len(on_mover) == 1
    # Nothing else in the field changed.
    assert len(search.detections) == len(on_mover)

    pm_dec = 2 * config.PIXEL_SCALE_ARCSEC * 1000.0  # mas/yr
    labelled = crossmatch.classify_changes(
        search.detections,
        gaia_for(wcs, STARS, mover=(mover_a, pm_dec)),
        [],
        mjd_a=MJD_A,
        mjd_b=MJD_B,
        g_complete=None,
        search=search,
        wcs=wcs,
    )
    assert all(c["classification"] == "catalogued_object" for c in labelled)
    assert all(c["gaia_match"]["source_id"] == "mover" for c in labelled)


def test_an_uncatalogued_new_source_is_a_candidate_signal():
    wcs, side = grid()
    a = render(side, STARS, seed=7)
    b = render(side, STARS + [(40, 18, 0.5)], seed=8)  # 50 sigma per pixel, nothing in Gaia.
    search = crossmatch.find_epoch_changes(a, b, wcs)
    labelled = crossmatch.classify_changes(
        search.detections, gaia_for(wcs, STARS), [], mjd_a=MJD_A, mjd_b=MJD_B,
        g_complete=None, search=search, wcs=wcs,
    )
    assert [(c["x"], c["y"], c["classification"]) for c in labelled] == [
        (40, side - 1 - 18, "candidate_signal")
    ]


def test_residual_on_a_static_star_with_consistent_flux_is_labelled_systematic():
    wcs, side = grid()
    a = render(side, STARS, seed=9)
    # One star 15 % fainter in B (a colour/wavelength effect), one doubled (real variability).
    dimmed, doubled = STARS[0], STARS[6]
    stars_b = [
        (x, y, p * (0.85 if (x, y, p) == dimmed else 2.0 if (x, y, p) == doubled else 1.0))
        for x, y, p in STARS
    ]
    b = render(side, stars_b, seed=10)
    search = crossmatch.find_epoch_changes(a, b, wcs)
    labelled = crossmatch.classify_changes(
        search.detections, gaia_for(wcs, STARS), [], mjd_a=MJD_A, mjd_b=MJD_B,
        g_complete=None, search=search, wcs=wcs,
    )
    on_dimmed = near(labelled, dimmed[0], dimmed[1], side)
    on_doubled = near(labelled, doubled[0], doubled[1], side)
    assert on_dimmed and all(c["classification"] == "catalogued_systematic" for c in on_dimmed)
    assert on_dimmed[0]["systematic"]["flux_ratio_b_over_a"] == pytest.approx(0.85, abs=0.05)
    assert on_doubled and all(c["classification"] == "catalogued_object" for c in on_doubled)
    assert all(c["systematic"] is None for c in on_doubled)

    ranked = crossmatch.rank_changes(labelled)
    assert ranked[0]["classification"] != "catalogued_systematic"
    assert ranked[-1]["classification"] == "catalogued_systematic"


def test_without_images_classification_never_claims_a_systematic():
    wcs, side = grid()
    a = render(side, STARS, seed=11)
    b = render(side, [(x, y, p * (0.85 if i == 0 else 1.0)) for i, (x, y, p) in enumerate(STARS)], seed=12)
    detections = crossmatch.detect_epoch_changes(a, b, wcs)
    labelled = crossmatch.classify_changes(
        detections, gaia_for(wcs, STARS), [], mjd_a=MJD_A, mjd_b=MJD_B, g_complete=None
    )
    assert labelled and all(c["classification"] != "catalogued_systematic" for c in labelled)


def test_gaussian_smooth_keeps_flux_and_nan_holes():
    image = np.zeros((21, 21))
    image[10, 10] = 1.0
    image[3, 3] = np.nan
    out = crossmatch.gaussian_smooth(image, 1.0)
    assert np.isnan(out[3, 3])
    assert np.nansum(out) == pytest.approx(1.0, rel=1e-3)
    assert out[10, 10] == pytest.approx(1 / (2 * math.pi), rel=0.05)


def test_aperture_photometry_reports_saturated_cores_as_unknown():
    image = np.zeros((15, 15))
    image[7, 7] = 10.0
    flux, _ = crossmatch.aperture_photometry(image, 7, 7)
    assert flux == pytest.approx(10.0)
    image[7, 7] = np.nan
    assert math.isnan(crossmatch.aperture_photometry(image, 7, 7)[0])
