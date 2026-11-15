import numpy as np

from app import config, db, ephemeris, gaia, imaging, wise
from app.store import EpochImage
from tests.test_api import DEC, RA, client  # noqa: F811


def _seed_ready_timeline(service, patch, detector=3, size="medium", shift_epoch1_x=0.0):
    wcs, (side, _) = imaging.make_target_grid(patch.ra, patch.dec, config.SIZES_DEG[size])
    tl = service.store.claim_timeline(patch.id, detector)
    assert tl is not None

    # Place 4 slow Gaia stars in the field (in FITS coordinates)
    star_coords = [
        (15, 15),
        (42, 16),
        (16, 42),
        (43, 43),
    ]
    gaia_stars = []
    for i, (sx, sy) in enumerate(star_coords):
        sra, sdec = (float(v) for v in wcs.pixel_to_world_values(sx, sy))
        gaia_stars.append(
            gaia.GaiaSource(f"bg{i}", sra % 360.0, sdec, 1.0, 1.0, 2.0, 14.0, 1.1)
        )

    def make_frame(dx: float = 0.0, extra_peak: tuple[int, int, float] | None = None) -> bytes:
        arr = np.full((side, side), 1.0, dtype=np.float32)
        yy, xx = np.mgrid[0:side, 0:side]
        for sx, sy in star_coords:
            arr += (20.0 * np.exp(-((xx - (sx + dx)) ** 2 + (yy - sy) ** 2) / 1.5)).astype(np.float32)
        if extra_peak is not None:
            px, py, amp = extra_peak
            arr += (amp * np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / 1.2)).astype(np.float32)
        return imaging.to_npz(arr, np.ones_like(arr))

    # Epoch 0: baseline; Epoch 1: one change on bg0 (catalogued) + one uncatalogued peak at (30, 30)
    npz0 = make_frame(0.0)
    npz1 = make_frame(shift_epoch1_x, extra_peak=(30, 30, 35.0))

    # Also brighten bg0 in epoch 1 so it shows up as a catalogued_object change
    loaded1 = np.load(__import__("io").BytesIO(npz1))["image"].copy()
    yy, xx = np.mgrid[0:side, 0:side]
    loaded1 += (30.0 * np.exp(-((xx - 15) ** 2 + (yy - 15) ** 2) / 1.2)).astype(np.float32)
    npz1 = imaging.to_npz(loaded1, np.ones_like(loaded1))

    from datetime import datetime, timezone

    t0 = datetime(2025, 7, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mjd0 = ephemeris.REFERENCE_MJD - 180.0
    mjd1 = ephemeris.REFERENCE_MJD
    # Like the real build: float32 arrays live only on the largest size, the others are crops.
    big = imaging.grid_pixels(max(config.SIZES_DEG.values()))
    start = (big - side) // 2

    def on_large_grid(npz: bytes) -> bytes:
        canvas = np.full((big, big), 1.0, dtype=np.float32)
        canvas[start : start + side, start : start + side] = np.load(__import__("io").BytesIO(npz))["image"]
        return imaging.to_npz(canvas, np.ones_like(canvas))

    imgs = [
        EpochImage(0, size, t0, t0, mjd0, 4, 4, side, side, 0.0, 50.0, b"png0", None),
        EpochImage(1, size, t1, t1, mjd1, 4, 4, side, side, 0.0, 50.0, b"png1", None),
        EpochImage(0, "large", t0, t0, mjd0, 4, 4, big, big, 0.0, 50.0, b"png0", on_large_grid(npz0)),
        EpochImage(1, "large", t1, t1, mjd1, 4, 4, big, big, 0.0, 50.0, b"png1", on_large_grid(npz1)),
    ]
    service.store.complete_timeline(tl.id, imgs, 8, 8)
    return gaia_stars


def test_candidates_endpoint_separates_catalogued_and_candidate_signals(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    gaia_stars = _seed_ready_timeline(service, patch)

    monkeypatch.setattr(gaia, "query_cone", lambda *a, **k: gaia_stars)
    monkeypatch.setattr(wise, "query_cone", lambda *a, **k: [])

    r = http.get(f"/api/v1/patches/{patch.id}/candidates", params={"detector": 3, "size": "medium"})
    assert r.status_code == 200
    body = r.json()
    assert body["gaia_available"] is True
    assert body["truncated"] is False  # 2 changes, well under the cap
    classes = {c["classification"] for c in body["candidates"]}
    assert "catalogued_object" in classes
    assert "candidate_signal" in classes
    assert body["snr_threshold"] == 5.0
    assert body["counts"]["detected"] == len(body["candidates"])
    assert body["counts"]["changes"] + body["counts"]["likely_systematic"] == body["counts"]["detected"]
    assert body["normalisation"]["smoothing_sigma_px"] == 1.0

    raw = http.get(
        f"/api/v1/patches/{patch.id}/candidates",
        params={"detector": 3, "size": "medium", "normalise": "false"},
    ).json()
    assert raw["normalisation"]["flux_scale"] == 1.0
    assert raw["normalisation"]["smoothing_sigma_px"] == 0.0


def test_alignment_endpoint_detects_offset_warning(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    gaia_stars = _seed_ready_timeline(service, patch, shift_epoch1_x=1.5)

    monkeypatch.setattr(gaia, "query_cone", lambda *a, **k: gaia_stars)

    r = http.get(f"/api/v1/patches/{patch.id}/alignment", params={"detector": 3, "size": "medium"})
    assert r.status_code == 200
    epochs = r.json()["epochs"]
    assert len(epochs) == 2
    assert epochs[0]["status"] == "ok"
    assert epochs[1]["status"] == "offset_warning"
    assert abs(epochs[1]["median_dx_px"] - 1.5) < 0.2


def test_explore_suggested_uses_gaia_and_falls_back(client, monkeypatch):  # noqa: F811
    http, _ = client
    monkeypatch.setattr(
        gaia,
        "query_suggested_destinations",
        lambda **kwargs: [
            gaia.GaiaSource("4472832130114786688", 269.44, 4.74, -801.6, 10362.4, 546.9, 8.19, 2.83)
        ],
    )
    r = http.get("/api/v1/explore/suggested", params={"limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == gaia.PROVIDER
    assert body["destinations"][0]["source_id"] == "4472832130114786688"

    def fail_gaia(**kwargs):
        raise gaia.GaiaQueryError("down")

    monkeypatch.setattr(gaia, "query_suggested_destinations", fail_gaia)
    r_fb = http.get("/api/v1/explore/suggested", params={"ra": 10.0, "dec": 20.0, "limit": 2})
    assert r_fb.status_code == 200
    assert r_fb.json()["source"] == "curated_fallback"
    assert len(r_fb.json()["destinations"]) == 2


def test_sync_targets_catalogs_hydrates_gaia_and_keeps_cold_dwarf_fallback(client, monkeypatch):  # noqa: F811
    _, service = client

    def fake_gaia(ra, dec, radius_deg=0.05, g_max=18.0, limit=50):
        # Match Barnard's star, return empty for cold brown dwarfs like WISE 0855
        if abs(ra - 269.446) < 0.5:
            return [
                gaia.GaiaSource("4472832130114786688", 269.4485, 4.7396, -801.6, 10362.4, 546.9, 8.19, 2.83)
            ]
        return []

    def fake_wise(ra, dec, radius_deg=0.05, w2_max=17.5, limit=50):
        if abs(ra - 133.759) < 0.5:
            # Place CatWISE source at 2015.4 so it propagates onto (ra, dec) at 2026.2
            ra_2015, dec_2015 = ephemeris.expected_position(
                ra, dec, -8123.7, 673.2, wise.REF_EPOCH_MJD, ref_mjd=ephemeris.REFERENCE_MJD
            )
            return [wise.WiseSource("0855", ra_2015, dec_2015, -8123.7, 673.2, 17.45, 13.89)]
        return []

    monkeypatch.setattr(gaia, "query_cone", fake_gaia)
    monkeypatch.setattr(wise, "query_cone", fake_wise)

    summary = db.sync_targets_catalogs(service.store)
    assert summary["barnards-star"]["gaia"] == "matched:4472832130114786688"
    assert summary["wise-0855"]["gaia"] == "no_match"
    assert summary["wise-0855"]["wise"] == "matched:0855"

    barnard = service.store.get_target("barnards-star")
    wise0855 = service.store.get_target("wise-0855")
    assert barnard is not None and barnard["gaia_source_id"] == "4472832130114786688"
    assert wise0855 is not None and wise0855["wise_w1_w2_color"] == 3.56


def test_model1_uses_real_gaia_and_wise_crossmatch_when_available(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=133.759, dec=-7.242)

    monkeypatch.setattr(gaia, "query_cone", lambda *a, **k: [])
    monkeypatch.setattr(
        wise,
        "query_cone",
        lambda *a, **k: [wise.WiseSource("w0855", 133.759, -7.242, -8123.7, 673.2, 17.45, 13.89)],
    )

    # Measured data with a mover, so Model 1 has an event and asks for the cross-match.
    from tests.test_real_science import seed_exposures, seed_moving_timeline

    seed_exposures(service.store, patch)
    seed_moving_timeline(service.store, patch, shift_px=2.0)
    r = http.post("/api/v1/models/classify-event", json={"patch_id": patch.id})
    assert r.status_code == 200 and r.json()["available"] is True
    assert r.json()["feature_vector"]["wise_w1_w2_color"] == 3.56
    saved = service.store.patch_crossmatches.get(patch.id)
    assert saved is not None
    assert saved["wise_crossmatch_json"]["w1_w2_color"] == 3.56
