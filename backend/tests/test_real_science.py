"""The science bundle measured on a patch's own data (real_science), with no demo profile."""

from datetime import datetime, timezone

import numpy as np
from fastapi.testclient import TestClient

from app import config, imaging, main, metrics, models, real_science, science_catalogs
from app.store import EpochImage
from tests.memory_store import MemoryStore

RA, DEC = 150.1, 2.2
VISITS_MJD = (61000.0, 61180.0, 61360.0)


def _flux_ujy(lam_um: float) -> float:
    """A smooth, cool-object-like SED (µJy): rising to a 4 µm peak."""
    return float(800.0 + 600.0 * np.exp(-((lam_um - 4.0) ** 2) / 0.8))


def seed_exposures(store, patch, *, saturated=False, visit_scale=(1.0, 1.0, 1.0), seed=3):
    """Three visits, the same 40 channels in each: per-exposure flux with 1 % noise."""
    rng = np.random.default_rng(seed)
    channels = [ch for ch in science_catalogs.SPHEREX_102_CHANNELS if not ch.is_blankch][::2][:40]
    rows = []
    for visit, (mjd0, scale) in enumerate(zip(VISITS_MJD, visit_scale)):
        for k, ch in enumerate(channels):
            flux = _flux_ujy(ch.lambda_c_um) * scale * (1 + 0.01 * rng.normal())
            mjd = mjd0 + 0.05 * k
            rows.append({
                "patch_id": patch.id, "timeline_id": None, "detector": ch.band, "epoch_index": visit,
                "uri": f"ibe/x/{visit}/{k}.fits", "release": "dr1", "energy_bandpassname": "x",
                "mjd_start": mjd, "mjd_end": mjd + 0.001, "mid_mjd": mjd,
                "cutout_center_ra": patch.ra, "cutout_center_dec": patch.dec, "cutout_size_deg": 0.35,
                "wavelength_um": ch.lambda_c_um, "channel_id": ch.channel_id,
                "aperture_flux_ujy": flux, "aperture_sigma_stat_ujy": 0.01 * flux,
                "aperture_sigma_reported_ujy": 0.0316 * flux,
                "local_background_mjy_sr": 0.0, "local_background_sigma_mjy_sr": 0.0,
                "aperture_peak_offset_px": 0.2, "saturated_near_target": saturated,
                "clean_pixel_fraction": 0.97, "science_bad_fraction": 0.03,
            })
    store.save_nasa_sector_exposures(rows)


def seed_moving_timeline(store, patch, detector=3, shift_px=2.0):
    """A ready timeline whose two epochs (float data on the large grid) show the central star
    moving ``shift_px`` east-west, among six still stars used to scale the epochs."""
    big = imaging.grid_pixels(max(config.SIZES_DEG.values()))
    c = (big - 1) / 2
    yy, xx = np.mgrid[0:big, 0:big]
    still = [(c - 30, c - 25), (c + 28, c - 31), (c - 33, c + 29), (c + 31, c + 27), (c, c - 40), (c + 40, c)]

    def frame(dx: float, seed: int) -> bytes:
        arr = np.full((big, big), 1.0)
        for sx, sy in still:
            arr += 40.0 * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / 1.5)
        arr += 60.0 * np.exp(-((xx - (c + dx)) ** 2 + (yy - c) ** 2) / 1.5)
        arr += np.random.default_rng(seed).normal(0, 0.05, arr.shape)
        return imaging.to_npz(arr.astype(np.float32), np.full(arr.shape, 0.0025, dtype=np.float32))

    tl = store.claim_timeline(patch.id, detector)
    t0, t1 = datetime(2025, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, tzinfo=timezone.utc)
    images = [
        EpochImage(0, "large", t0, t0, VISITS_MJD[0], 16, 16, big, big, 0.0, 50.0, b"p0", frame(-shift_px / 2, 1)),
        EpochImage(1, "large", t1, t1, VISITS_MJD[-1], 16, 16, big, big, 0.0, 50.0, b"p1", frame(shift_px / 2, 2)),
    ]
    store.complete_timeline(tl.id, images, 16, 16)


def measured_client(*, saturated=False, timeline=True):
    store = MemoryStore()
    patch = store.create_patch(RA, DEC, None)
    seed_exposures(store, patch, saturated=saturated)
    if timeline:
        seed_moving_timeline(store, patch)
    main.app.dependency_overrides[main.get_store] = lambda: store
    main._last_forced_analysis.clear()
    return TestClient(main.app), store, patch


def test_spectrum_102_is_the_measured_channel_medians_in_mjy():
    store = MemoryStore()
    patch = store.create_patch(RA, DEC, None)
    seed_exposures(store, patch)
    measured = real_science.measured_spectrum(store.list_nasa_sector_exposures(patch.id))
    spectrum, reason = real_science.spectrum_102(measured)
    assert reason is None and spectrum["data_source"] == "measured"
    assert spectrum["valid_channel_count"] == 40
    assert spectrum["flux_mjy"][50] is None and spectrum["flux_mjy"][51] is None  # BLANKCH 51-52
    i = next(k for k, ok in enumerate(spectrum["valid_mask"]) if ok)
    expected = _flux_ujy(science_catalogs.SPHEREX_102_CHANNELS[i].lambda_c_um) / 1000
    assert abs(spectrum["flux_mjy"][i] - expected) < 0.03 * expected
    assert len(metrics.compute_all_17_spectral_indices(spectrum)) == 17


def test_light_curve_follows_the_object_not_the_filter_sweep():
    store = MemoryStore()
    patch = store.create_patch(RA, DEC, None)
    # The object fades by 20 % in the last visit; each visit samples many wavelengths.
    seed_exposures(store, patch, visit_scale=(1.0, 1.0, 0.8))
    measured = real_science.measured_spectrum(store.list_nasa_sector_exposures(patch.id))
    curve, reason = real_science.light_curve(measured)
    assert reason is None and len(curve["times_mjd"]) == 3
    first, _, last = curve["fluxes_mjy"]
    # The SED changes by ~2x across channels, yet the visits differ only by the real fade.
    assert 0.75 < last / first < 0.88
    assert all(s > 0 for s in curve["sigmas_mjy"])


def test_light_curve_and_spectrum_say_why_when_the_star_saturates():
    store = MemoryStore()
    patch = store.create_patch(RA, DEC, None)
    seed_exposures(store, patch, saturated=True)
    measured = real_science.measured_spectrum(store.list_nasa_sector_exposures(patch.id))
    spectrum, reason = real_science.spectrum_102(measured)
    assert spectrum is None and "saturates" in reason
    curve, reason = real_science.light_curve(measured)
    assert curve is None and reason


def test_model1_features_are_measured_on_the_epoch_images():
    store = MemoryStore()
    patch = store.create_patch(RA, DEC, None)
    seed_exposures(store, patch)
    seed_moving_timeline(store, patch, shift_px=2.0)
    exposures = store.list_nasa_sector_exposures(patch.id)
    fv, info = real_science.model1_features(store, patch, None, exposures, None, None, None)
    assert info["detector"] == 3 and info["epoch_a"] == 0 and info["epoch_b"] == 1
    assert fv["z_dipole"] > 10 and fv["dipole_symmetry"] > 0.6
    assert 6.0 <= fv["angular_shift_arcsec"] <= 3 * config.PIXEL_SCALE_ARCSEC
    assert abs(fv["p_clean_flags"] - 0.97) < 1e-6
    # No cross-match: those features are left neutral and listed, never invented.
    assert "gaia_match_dist_arcsec" not in fv
    assert "gaia_match_dist_arcsec" in info["features_unavailable"]


def test_endpoints_serve_the_measured_bundle_not_a_demo_profile():
    client, store, patch = measured_client()
    try:
        # Old simulated rows (v1) are ignored.
        demo = models.run_model1_event_classifier(models.DEMO_PROFILE_SPECS["r-draconis"]["features"])
        store.save_model1_attribution(patch.id, -1, demo)
        for path in ("spectrum", "metrics", "models/event", "models/spectrum", "models/forecast"):
            body = client.get(f"/api/v1/patches/{patch.id}/{path}").json()
            assert body["simulated"] is False, path
            assert "Measured" in body["data_note"], path
        event = client.get(f"/api/v1/patches/{patch.id}/models/event").json()
        assert event["available"] is True and event["model_version"] == real_science.MEASURED_VERSION
        assert event["researcher_level2"]["measurement"]["detector"] == 3
        metrics_body = client.get(f"/api/v1/patches/{patch.id}/metrics").json()
        assert len(metrics_body["light_curve"]["times_mjd"]) == 3
        assert 0.0 <= metrics_body["confidence"]["c_global"] <= 100.0
        spectrum = client.get(f"/api/v1/patches/{patch.id}/spectrum").json()
        assert spectrum["available"] is True and len(spectrum["indices"]) == 17
        forecast = client.get(f"/api/v1/patches/{patch.id}/models/forecast").json()
        assert forecast["researcher_level2"]["light_curve"]["times_mjd"][0] > 60000
    finally:
        main.app.dependency_overrides.clear()


def test_a_part_that_cannot_be_measured_is_unavailable_with_its_reason():
    client, _, patch = measured_client(saturated=True, timeline=False)
    try:
        for path in ("spectrum", "models/event", "models/spectrum", "models/forecast"):
            body = client.get(f"/api/v1/patches/{patch.id}/{path}").json()
            assert body["available"] is False and body["simulated"] is False, path
            assert body["reason"], path
        metrics_body = client.get(f"/api/v1/patches/{patch.id}/metrics").json()
        assert metrics_body["confidence"] is None and metrics_body["light_curve"] is None
        assert set(metrics_body["unavailable"]) >= {"spectrum", "light_curve", "model1_event"}
    finally:
        main.app.dependency_overrides.clear()


def test_demo_profiles_only_answer_an_explicit_scenario():
    client, _, patch = measured_client()
    try:
        body = client.post(
            "/api/v1/models/classify-spectrum", json={"patch_id": patch.id, "scenario": "r-draconis"}
        ).json()
        assert body["simulated"] is True and "Simulated" in body["data_note"]
        measured = client.post("/api/v1/models/classify-spectrum", json={"patch_id": patch.id}).json()
        assert measured["simulated"] is False and measured["available"] is True
    finally:
        main.app.dependency_overrides.clear()


def test_reads_reuse_the_stored_measured_results():
    client, _, patch = measured_client()
    try:
        models_ = ("event", "spectrum", "forecast")
        ids = [client.get(f"/api/v1/patches/{patch.id}/models/{m}").json()["id"] for m in models_]
        client.get(f"/api/v1/patches/{patch.id}/metrics")
        again = [client.get(f"/api/v1/patches/{patch.id}/models/{m}").json()["id"] for m in models_]
        assert again == ids
    finally:
        main.app.dependency_overrides.clear()
