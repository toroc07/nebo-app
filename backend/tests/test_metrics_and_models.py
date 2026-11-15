"""Verification suite for SPHEREx metrics, 17 spectral indices, Models 1-3, and API endpoints."""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import imaging, main, metrics, models, science_catalogs
from tests.memory_store import MemoryStore


def _make_gaussian_cutout(
    size: int = 21,
    cx: float = 10.0,
    cy: float = 10.0,
    peak: float = 100.0,
    noise_sigma: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:size, 0:size]
    sigma_psf = 1.22 / 2.35482
    img = peak * np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2.0 * sigma_psf * sigma_psf)))
    var = np.full((size, size), noise_sigma ** 2, dtype=np.float64)
    return img, var


def test_psf_photometry_enforces_3pct_floor_and_photometry_mask():
    img, var = _make_gaussian_cutout(peak=5000.0, noise_sigma=0.2)
    flags = np.zeros_like(img, dtype=np.int64)
    # Corrupt one corner pixel inside the 5x5 aperture with SNOWBALL (0x08000000)
    flags[9, 9] = 0x08000000
    img[9, 9] = 1.0e7  # Must be ignored by MASK_PHOTOMETRY

    phot = metrics.extract_optimal_psf_photometry(img, var, flags=flags, center_xy=(10, 10))
    assert phot["flux_hat"] > 1000.0
    assert phot["flux_hat"] < 50000.0
    assert phot["sigma_reported"] >= 0.03 * abs(phot["flux_hat"]) - 1e-6
    assert phot["n_valid_pixels"] == 24


def test_psf_photometry_is_stable_for_a_moving_star():
    # A moving star (Barnard) lands on a different sub-pixel spot each epoch; flux must not jump.
    fluxes = []
    for cx, cy in [(10.0, 10.0), (10.4, 9.6), (9.5, 10.5), (11.0, 10.3)]:
        img, _ = _make_gaussian_cutout(cx=cx, cy=cy, peak=5000.0)
        var = 1.0 + img  # Poisson-like: the star dominates its own variance
        fluxes.append(metrics.extract_optimal_psf_photometry(img, var, center_xy=(cx, cy))["flux_hat"])
    assert max(fluxes) / min(fluxes) < 1.2, fluxes


def test_psf_snr_is_measured_and_grows_with_exposures():
    rng = np.random.default_rng(0)
    star, _ = _make_gaussian_cutout(peak=500.0)
    frame_var = np.full_like(star, 25.0)

    def snr(n: int) -> float:
        frames = [star + rng.normal(0.0, 5.0, star.shape) for _ in range(n)]
        image, variance = imaging.coadd(frames, [frame_var] * n)
        return metrics.extract_optimal_psf_photometry(image, variance, center_xy=(10, 10))["snr"]

    one, eight = snr(1), snr(8)
    assert eight > 2.0 * one  # ~sqrt(8) with real noise
    assert abs(one - 1 / 0.03) > 1.0 and abs(eight - 1 / 0.03) > 1.0  # not the 3% floor cap


def test_psf_photometry_without_variance_is_not_a_number():
    img, _ = _make_gaussian_cutout()
    phot = metrics.extract_optimal_psf_photometry(img, np.full_like(img, np.nan), center_xy=(10, 10))
    assert phot["snr"] is None and phot["sigma_stat"] is None and phot["flux_hat"] is None


def test_epoch_saturation_counts_frames_inside_the_epoch():
    from types import SimpleNamespace

    from app.service import mjd_to_datetime

    image = SimpleNamespace(start_utc=mjd_to_datetime(61000.0), end_utc=mjd_to_datetime(61010.0))
    exposures = [
        {"mjd_start": 61000.0, "saturated_near_target": True},
        {"mjd_start": 61005.0, "saturated_near_target": False},
        {"mjd_start": 61010.0, "saturated_near_target": True},
        {"mjd_start": 61007.0, "saturated_near_target": None},  # unknown: not counted
        {"mjd_start": 61200.0, "saturated_near_target": True},  # another epoch
    ]
    assert main._epoch_saturation(exposures, image) == {
        "saturated": True,
        "saturated_frames": 2,
        "checked_frames": 3,
        "total_frames": 4,
        "saturated_frac": 0.667,
    }
    clean = [{"mjd_start": 61001.0, "saturated_near_target": False}]
    assert main._epoch_saturation(clean, image)["saturated"] is False
    # One unchecked frame: not known to be clean.
    partial = clean + [{"mjd_start": 61002.0, "saturated_near_target": None}]
    assert main._epoch_saturation(partial, image)["saturated"] is None
    assert main._epoch_saturation([], image)["saturated"] is None
    assert main._epoch_saturation([], image)["saturated_frac"] is None


def test_epoch_coverage_flags_epochs_that_mix_bursts():
    from types import SimpleNamespace

    from app.service import mjd_to_datetime

    # One burst of 5 days: a single observing visit, no warning.
    short = SimpleNamespace(start_utc=mjd_to_datetime(61000.0), end_utc=mjd_to_datetime(61005.0))
    exposures = [
        {"mjd_start": 61000.0, "wavelength_um": 1.20},
        {"mjd_start": 61002.0, "wavelength_um": 1.31},
        {"mjd_start": 61005.0, "wavelength_um": None},  # unknown wavelength: skipped
        {"mjd_start": 61300.0, "wavelength_um": 2.00},  # another epoch
    ]
    coverage = main._epoch_coverage(exposures, short)
    assert coverage["span_days"] == pytest.approx(5.0)
    assert coverage["max_gap_days"] == pytest.approx(3.0)
    assert coverage["mixed_bursts"] is False
    assert coverage["wavelength_um"] == {"min": 1.2, "max": 1.31}

    # 47 days with a 25-day hole: small spans were folded together, so it is flagged.
    long = SimpleNamespace(start_utc=mjd_to_datetime(61000.0), end_utc=mjd_to_datetime(61047.0))
    mixed = [{"mjd_start": m, "wavelength_um": None} for m in (61000.0, 61010.0, 61035.0, 61047.0)]
    coverage = main._epoch_coverage(mixed, long)
    assert coverage["mixed_bursts"] is True
    assert coverage["max_gap_days"] == pytest.approx(25.0)
    assert coverage["wavelength_um"] is None


def test_difference_snr_and_mahalanobis_displacement():
    img1, var1 = _make_gaussian_cutout(cx=10.0, cy=10.0, peak=120.0, noise_sigma=0.5)
    img2, var2 = _make_gaussian_cutout(cx=12.0, cy=10.0, peak=120.0, noise_sigma=0.5)

    diff = metrics.compute_difference_snr_map(img1, var1, img2, var2)
    assert diff["z_dipole"] > 10.0
    assert diff["dipole_symmetry"] > 0.85
    assert diff["angular_shift_arcsec"] > 6.0

    astro = metrics.compute_centroid_and_mahalanobis(img1, var1, img2, var2, mjd_t1=60800.0, mjd_t2=60982.625)
    assert astro["mahalanobis_dm"] >= 3.0
    assert astro["is_significant_motion"] is True
    assert astro["shift_arcsec"] > 6.0


def test_variability_metrics_and_global_confidence():
    t = np.array([60800.0, 60840.0, 60880.0, 60920.0, 60960.0, 61000.0])
    y = 100.0 + 30.0 * np.sin(2.0 * math.pi * (t - 60800.0) / 120.0)
    s = np.full_like(y, 1.5)
    var_res = metrics.compute_variability_metrics(t, y, s)
    assert var_res["chi2_var_reduced"] > 3.0
    assert var_res["is_variable"] is True
    assert var_res["lomb_scargle_power"] > 0.5

    conf = metrics.compute_global_confidence_score(
        snr=15.0, dipole_symmetry=0.95, angular_shift_px=1.0, active_flag_names=(), q_fit_epsf=1.0
    )
    assert 85.0 <= conf["c_global"] <= 100.0

    conf_art = metrics.compute_global_confidence_score(
        snr=15.0, dipole_symmetry=0.95, angular_shift_px=1.0, active_flag_names=("SNOWBALL",), q_fit_epsf=1.0
    )
    assert conf_art["c_global"] == 0.0


def test_17_spectral_indices_on_catalogue_targets_and_blankch_null():
    # WISE 0855: ultra-cold Y dwarf -> COLOR_PLANET_X > 0.70, CH4 & H2O ice
    spec_wise = models.build_demo_spectrum_payload("wise-0855")
    assert spec_wise["flux_mjy"][50] is None and spec_wise["flux_mjy"][51] is None
    assert spec_wise["valid_mask"][50] is False and spec_wise["valid_mask"][51] is False

    idx_wise = {r["index_code"]: r for r in metrics.compute_all_17_spectral_indices(spec_wise)}
    assert len(idx_wise) == 17
    assert idx_wise["COLOR_PLANET_X"]["is_valid"] is True
    assert idx_wise["COLOR_PLANET_X"]["value"] > 0.70
    assert idx_wise["COLOR_PLANET_X"]["is_significant_3s"] is True
    assert idx_wise["IND_CH4_33"]["value"] > 0.3

    # RW Aurigae: YSO disk -> dust excess + Pa-beta & Br-alpha emission
    spec_rw = models.build_demo_spectrum_payload("rw-aurigae")
    idx_rw = {r["index_code"]: r for r in metrics.compute_all_17_spectral_indices(spec_rw)}
    assert idx_rw["COLOR_YSO_DUST"]["value"] > 1.2
    assert idx_rw["IND_BR_ALPHA"]["value"] > 0.0
    assert idx_rw["IND_PA_BETA"]["value"] > 0.0

    # R Draconis: AGB Mira -> CO 2-0 overtone via blue extrapolation avoiding BLANKCH 51-52
    spec_rdra = models.build_demo_spectrum_payload("r-draconis")
    idx_rdra = {r["index_code"]: r for r in metrics.compute_all_17_spectral_indices(spec_rdra)}
    assert idx_rdra["IND_CO_23"]["is_valid"] is True
    assert idx_rdra["IND_CO_23"]["value"] > 0.15


def test_models_1_2_3_and_artifact_veto_handshake():
    # Model 1: Moving object, Variable star, Artifact, and He I Airglow hard bound
    m1_wise = models.run_model1_event_classifier(models.DEMO_PROFILE_SPECS["wise-0855"]["features"])
    assert m1_wise["predicted_class"] == "MOVING_OBJECT"
    assert math.isclose(sum(m1_wise["probabilities"].values()), 1.0, abs_tol=1e-4)
    assert len(m1_wise["treeshap_values"]["top_drivers"]) == 5

    m1_rw = models.run_model1_event_classifier(models.DEMO_PROFILE_SPECS["rw-aurigae"]["features"])
    assert m1_rw["predicted_class"] == "VARIABLE_STAR_OR_TRANSIENT"

    m1_art = models.run_model1_event_classifier(models.DEMO_PROFILE_SPECS["artifact_injection"]["features"])
    assert m1_art["predicted_class"] == "INSTRUMENTAL_ARTIFACT"

    he_airglow_fv = dict(models.DEMO_PROFILE_SPECS["rw-aurigae"]["features"])
    he_airglow_fv.update({"is_he_1083_channel": 1.0, "bg_gradient_ratio": 4.2, "q_fit_epsf": 2.5})
    m1_air = models.run_model1_event_classifier(he_airglow_fv)
    assert m1_air["predicted_class"] == "AIRGLOW_OR_ZODI_STRIPE"
    # P0-3: hand-set weights are not calibrated, so no class may read 0% or 100%.
    for m1 in (m1_wise, m1_rw, m1_art, m1_air):
        assert all(0.02 <= v <= 0.92 for v in m1["probabilities"].values()), m1["probabilities"]
        assert m1["citizen_level1"]["confidence_score_pct"] < 100

    # Model 2: All 5 catalogue targets + comet classified correctly using <= 100 valid channels
    expected_m2 = {
        "wise-0855": "ULTRACOLD_Y_DWARF",
        "eps-indi-b": "COLD_BROWN_DWARF_T",
        "barnards-star": "HIGH_PROPER_MOTION_M_DWARF",
        "rw-aurigae": "YOUNG_STELLAR_OBJECT_ACCRETION",
        "r-draconis": "PULSATING_MIRA_VARIABLE",
        "solar_system_mover": "SOLAR_SYSTEM_COMET",
    }
    for slug, expected_cls in expected_m2.items():
        spec = models.build_demo_spectrum_payload(slug)
        m2 = models.run_model2_spectral_classifier(spec)
        assert m2["valid_channels_used"] == 100
        assert m2["predicted_class"] == expected_cls
        assert math.isclose(sum(m2["bayesian_posteriors"].values()), 1.0, abs_tol=1e-4)
        assert all(0.01 <= v <= 0.92 for v in m2["bayesian_posteriors"].values())

    # Model 3: RW Aurigae triggers alert; artifact_injection is VETOED by Model 1
    rw_cfg = models.DEMO_PROFILE_SPECS["rw-aurigae"]
    rw_sig = [science_catalogs.compute_reported_sigma(f, 0.015 * f) for f in rw_cfg["fluxes_mjy"]]
    m3_rw = models.run_model3_temporal_forecast(
        rw_cfg["times_mjd"],
        rw_cfg["fluxes_mjy"],
        rw_sig,
        ra_deg=76.956587,
        dec_deg=30.40129,
        model1_result=m1_rw,
    )
    assert m3_rw["alert_triggered"] is True
    assert m3_rw["z_alert"] >= 3.0
    assert len(m3_rw["forecast_series"]) == 13

    art_cfg = models.DEMO_PROFILE_SPECS["artifact_injection"]
    art_sig = [science_catalogs.compute_reported_sigma(f, 0.015 * f) for f in art_cfg["fluxes_mjy"]]
    m3_art = models.run_model3_temporal_forecast(
        art_cfg["times_mjd"],
        art_cfg["fluxes_mjy"],
        art_sig,
        ra_deg=10.0,
        dec_deg=20.0,
        model1_result=m1_art,
    )
    assert m3_art["alert_triggered"] is False
    assert m3_art["citizen_level1"]["vetoed_by_model1"] is True


def test_api_end_to_end_science_pipeline_and_votes():
    store = MemoryStore()
    store.upsert_targets(
        [
            {
                "slug": "wise-0855",
                "name": "WISE 0855-0714",
                "ra": 133.75931,
                "dec": -7.242145,
                "kind": "brown_dwarf",
                "note": "Coldest known brown dwarf.",
                "pm_ra_mas_yr": -8123.7,
                "pm_dec_mas_yr": 673.2,
                "recommended_detector": 6,
            }
        ]
    )
    patch = store.create_patch(133.75931, -7.242145, "wise-0855")
    main.app.dependency_overrides[main.get_store] = lambda: store
    try:
        client = TestClient(main.app)

        r_an = client.post(f"/api/v1/patches/{patch.id}/analyze", json={"force_recompute": True})
        assert r_an.status_code == 200
        body = r_an.json()
        assert body["model1_event"]["predicted_class"] == "MOVING_OBJECT"
        assert body["model2_spectrum"]["predicted_class"] == "ULTRACOLD_Y_DWARF"
        assert body["spectrum"]["blankch_51_is_null"] is True
        assert body["spectrum"]["blankch_52_is_null"] is True

        r_spec = client.get(f"/api/v1/patches/{patch.id}/spectrum")
        assert r_spec.status_code == 200
        assert len(r_spec.json()["indices"]) == 17

        r_met = client.get(f"/api/v1/patches/{patch.id}/metrics")
        assert r_met.status_code == 200
        assert 0.0 <= r_met.json()["confidence"]["c_global"] <= 100.0

        r_m1 = client.post(
            "/api/v1/models/classify-event",
            json={"patch_id": patch.id, "feature_vector": models.DEMO_PROFILE_SPECS["wise-0855"]["features"]},
        )
        assert r_m1.status_code == 200
        assert r_m1.json()["predicted_class"] == "MOVING_OBJECT"

        r_m2 = client.post("/api/v1/models/classify-spectrum", json={"patch_id": patch.id})
        assert r_m2.status_code == 200
        assert r_m2.json()["predicted_class"] == "ULTRACOLD_Y_DWARF"

        r_m3 = client.post("/api/v1/models/forecast-temporal", json={"patch_id": patch.id})
        assert r_m3.status_code == 200
        assert "predicted_cone" in r_m3.json()

        r_vote = client.post(
            f"/api/v1/patches/{patch.id}/votes",
            json={"epoch_index": 0, "vote": "MOVER", "voter_token": "tester-1"},
        )
        assert r_vote.status_code == 200
        r_votes = client.get(f"/api/v1/patches/{patch.id}/votes")
        assert r_votes.status_code == 200
        assert len(r_votes.json()) == 1
        assert r_votes.json()[0]["vote"] == "MOVER"
    finally:
        main.app.dependency_overrides.clear()


def _science_client():
    store = MemoryStore()
    store.upsert_targets(
        [
            {
                "slug": "wise-0855",
                "name": "WISE 0855-0714",
                "ra": 133.75931,
                "dec": -7.242145,
                "kind": "brown_dwarf",
                "note": "Coldest known brown dwarf.",
                "pm_ra_mas_yr": -8123.7,
                "pm_dec_mas_yr": 673.2,
                "recommended_detector": 6,
            }
        ]
    )
    patch = store.create_patch(133.75931, -7.242145, "wise-0855")
    main.app.dependency_overrides[main.get_store] = lambda: store
    main._last_forced_analysis.clear()
    return TestClient(main.app), store, patch


def test_science_results_from_demo_profiles_are_labelled_simulated():
    client, _, patch = _science_client()
    try:
        for path in ("spectrum", "metrics", "models/event", "models/spectrum", "models/forecast"):
            body = client.get(f"/api/v1/patches/{patch.id}/{path}").json()
            assert body["simulated"] is True, path
            assert "Simulated" in body["data_note"], path
        # Data the caller sends is labelled as such and not stored on the patch.
        fv = models.DEMO_PROFILE_SPECS["artifact_injection"]["features"]
        sent = client.post("/api/v1/models/classify-event", json={"patch_id": patch.id, "feature_vector": fv})
        assert sent.json()["simulated"] is False
        stored = client.get(f"/api/v1/patches/{patch.id}/models/event").json()
        assert stored["predicted_class"] == "MOVING_OBJECT"
    finally:
        main.app.dependency_overrides.clear()


def test_reads_reuse_stored_model_results():
    client, _, patch = _science_client()
    try:
        first = client.get(f"/api/v1/patches/{patch.id}/metrics")
        assert first.status_code == 200
        ids = [client.get(f"/api/v1/patches/{patch.id}/models/{m}").json()["id"] for m in ("event", "spectrum", "forecast")]
        client.get(f"/api/v1/patches/{patch.id}/metrics")
        again = [client.get(f"/api/v1/patches/{patch.id}/models/{m}").json()["id"] for m in ("event", "spectrum", "forecast")]
        assert again == ids
    finally:
        main.app.dependency_overrides.clear()


def test_forced_analysis_has_a_cooldown():
    client, _, patch = _science_client()
    try:
        url = f"/api/v1/patches/{patch.id}/analyze"
        assert client.post(url, json={"force_recompute": True}).status_code == 200
        busy = client.post(url, json={"force_recompute": True})
        assert busy.status_code == 429 and int(busy.headers["Retry-After"]) > 0
        # Reading the stored results is not limited.
        assert client.post(url, json={}).status_code == 200
    finally:
        main.app.dependency_overrides.clear()


def test_bad_model_inputs_are_rejected_not_500():
    client, _, _ = _science_client()
    try:
        short = client.post(
            "/api/v1/models/classify-spectrum",
            json={"spectrum": {"flux_mjy": [1, 2], "valid_mask": [True, True]}},
        )
        assert short.status_code == 422
        mismatch = client.post(
            "/api/v1/models/forecast-temporal",
            json={"times_mjd": [1.0, 2.0, 3.0], "fluxes_mjy": [1.0, 2.0, 3.0], "sigmas_mjy": [0.1]},
        )
        assert mismatch.status_code == 422
        too_long = client.post(
            "/api/v1/models/forecast-temporal",
            json={"times_mjd": list(range(501)), "fluxes_mjy": [1.0] * 501},
        )
        assert too_long.status_code == 422
    finally:
        main.app.dependency_overrides.clear()
    # The model itself also tolerates a short spectrum instead of raising IndexError.
    assert models.run_model2_spectral_classifier({"flux_mjy": [1.0], "valid_mask": [True]})


def test_vote_listing_never_exposes_voter_tokens():
    client, _, patch = _science_client()
    try:
        client.post(f"/api/v1/patches/{patch.id}/votes", json={"vote": "MOVER", "voter_token": "secret-1"})
        votes = client.get(f"/api/v1/patches/{patch.id}/votes").json()
        assert len(votes) == 1 and "voter_token" not in votes[0]
    finally:
        main.app.dependency_overrides.clear()


def test_measured_spectrum_uses_real_exposures_and_leaves_out_saturated_ones():
    exposures = [
        {"aperture_flux_ujy": 100.0, "aperture_sigma_reported_ujy": 5.0, "wavelength_um": 1.2,
         "channel_id": 10, "detector": 2, "epoch_index": 0, "mid_mjd": 61000.0},
        {"aperture_flux_ujy": 110.0, "aperture_sigma_reported_ujy": 5.0, "wavelength_um": 1.21,
         "channel_id": 10, "detector": 2, "epoch_index": 1, "mid_mjd": 61200.0},
        {"aperture_flux_ujy": 300.0, "wavelength_um": 4.5, "channel_id": 95, "detector": 6,
         "epoch_index": 0, "mid_mjd": 61000.0, "aperture_sigma_stat_ujy": 9.0},
        # Saturated near the object: only a lower limit, so it is not a point of the spectrum.
        {"aperture_flux_ujy": 50.0, "wavelength_um": 2.0, "channel_id": 40,
         "saturated_near_target": True},
        # No measurement (aperture had flagged pixels).
        {"aperture_flux_ujy": None, "wavelength_um": 3.0, "channel_id": 70},
    ]
    spec = main.measured_spectrum(exposures)
    assert spec["measured"] is True
    assert [p["wavelength_um"] for p in spec["points"]] == [1.2, 1.21, 4.5]
    assert spec["excluded_saturated"] == 1 and spec["excluded_missing"] == 1
    ch10 = next(c for c in spec["channels"] if c["channel_id"] == 10)
    assert ch10["n"] == 2 and ch10["flux_ujy"] == 105.0
    ch95 = next(c for c in spec["channels"] if c["channel_id"] == 95)
    assert ch95["n"] == 1 and ch95["sigma_ujy"] == 9.0
