"""PostgresStore against a real database. Skipped unless NEBO_TEST_DATABASE_URL is set.

Use a throwaway database: the tests create the schema and delete the rows they insert.
"""

import os
from datetime import datetime, timezone

import pytest

from app import config
from app.db import SCHEMA_PATH
from app.science_catalogs import SPHEREX_17_INDICES, SPHEREX_102_CHANNELS
from app.store import EpochImage
from app.targets import TARGETS

DSN = os.environ.get("NEBO_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DSN, reason="NEBO_TEST_DATABASE_URL is not set")


@pytest.fixture
def store():
    from app.store import PostgresStore

    pg = PostgresStore(DSN, max_size=4)
    pg.apply_schema(SCHEMA_PATH.read_text(encoding="utf-8"))
    pg.upsert_targets(TARGETS)
    pg.upsert_spherex_channels(SPHEREX_102_CHANNELS)
    pg.upsert_spectral_indices(SPHEREX_17_INDICES)
    created: list[int] = []
    pg.created_patches = created
    yield pg
    with pg.pool.connection() as conn:
        conn.execute("DELETE FROM patches WHERE id = ANY(%s)", (created,))
    pg.close()


def _image(epoch: int, size: str) -> EpochImage:
    now = datetime.now(timezone.utc)
    npz = b"NPZDATA" if size == "large" else None
    return EpochImage(epoch, size, now, now, 61000.0 + epoch, 8, 6, 31, 31, 0.0, 1.0, b"\x89PNG", npz=npz)


def test_targets_round_trip(store):
    assert store.get_target("wise-0855")["recommended_detector"] == 6
    assert len(store.list_targets()) >= len(TARGETS)


def test_patch_lookup_and_timeline_lifecycle(store):
    patch = store.create_patch(123.456, -45.0, None)
    store.created_patches.append(patch.id)
    assert store.find_patch_near(123.456, -45.0 + 5 / 3600, 30 / 3600).id == patch.id

    claimed = store.claim_timeline(patch.id, 2)
    assert claimed is not None and claimed.status == "building"
    assert store.claim_timeline(patch.id, 2) is None  # Already being built.

    store.update_progress(claimed.id, "downloading", 3, 10)
    assert store.get_timeline(patch.id, 2).progress_done == 3

    images = [_image(e, s) for e in range(2) for s in config.SIZES_DEG]
    store.complete_timeline(claimed.id, images, frames_found=20, frames_used=12)
    timeline = store.get_timeline(patch.id, 2)
    assert timeline.status == "ready" and timeline.frames_used == 12

    medium = store.list_images(claimed.id, "medium")
    assert [i.epoch_index for i in medium] == [0, 1]
    assert store.get_png(medium[0].id) == b"\x89PNG"
    assert store.get_npz(medium[0].id) is None
    large = store.list_images(claimed.id, "large")
    assert large[0].has_npz is True
    assert store.get_npz(large[0].id) == b"NPZDATA"
    assert len(store.list_sector_coordinates(patch.id)) == 4
    assert any(p["id"] == patch.id for p in store.list_patches_with_data())


def test_science_tables_sectors_and_models_round_trip(store):
    patch = store.create_patch(200.0, -30.0, None)
    store.created_patches.append(patch.id)

    exposures_saved = store.save_nasa_sector_exposures(
        [
            {
                "patch_id": patch.id,
                "timeline_id": None,
                "detector": 3,
                "epoch_index": 0,
                "uri": "ibe/data/spherex/qr3/level2/test/D3.fits",
                "release": "qr3",
                "plane_id": "plane-123",
                "energy_bandpassname": "SPHEREx-D3",
                "nasa_poly_icrs": "POLYGON ICRS 199.9 -30.1 200.1 -30.1 200.1 -29.9 199.9 -29.9",
                "mjd_start": 60900.0,
                "mjd_end": 60900.1,
                "mid_mjd": 60900.05,
                "cutout_center_ra": 200.0,
                "cutout_center_dec": -30.0,
                "cutout_size_deg": 0.3536,
                "channel_id": 41,
                "aperture_flux_ujy": 100.0,
                "aperture_sigma_stat_ujy": 4.0,
                "aperture_sigma_reported_ujy": 5.0,
            }
        ]
    )
    assert exposures_saved == 1
    assert len(store.list_nasa_sector_exposures(patch.id, detector=3)) == 1

    flux = [10.0] * 102
    flux[50] = 0.0
    flux[51] = 0.0
    spec = store.save_patch_spectrum(
        patch.id,
        -1,
        {
            "flux_mjy": flux,
            "variance_mjy2": [0.25] * 102,
            "valid_mask": [True] * 102,
            "channel_hit_counts": [2] * 102,
        },
        indices=[{"index_code": "COLOR_PLANET_X", "value": 0.82, "uncertainty": 0.08}],
    )
    assert spec["flux_mjy"][50] is None and spec["flux_mjy"][51] is None
    assert spec["valid_mask"][50] is False and spec["valid_mask"][51] is False

    m1 = store.save_model1_attribution(
        patch.id,
        -1,
        {
            "feature_vector": {"psf_chi2": 1.1},
            "predicted_class": "MOVING_OBJECT",
            "probabilities": {"MOVING_OBJECT": 0.9, "VARIABLE_STAR_OR_TRANSIENT": 0.05, "INSTRUMENTAL_ARTIFACT": 0.05},
            "treeshap_values": {"psf_chi2": 0.3},
            "citizen_level1": {"badge": "Real Source"},
            "researcher_level2": {"temperature_t": 1.0},
        },
    )
    m3 = store.save_model3_forecast(
        patch.id,
        {
            "model1_attribution_id": m1["id"],
            "gp_hyperparams": {"tau_days": 120.0},
            "forecast_series": [{"mjd": 61200.0, "flux": 10.5}],
            "predicted_cone": {"cone_radius_deg": 0.01},
            "z_alert": 3.4,
            "alert_triggered": True,
            "citizen_level1": {"status": "Forecast ready"},
            "researcher_level2": {"model1_handshake": True},
        },
    )
    assert m3["model1_attribution_id"] == m1["id"]
    assert store.get_model3_forecast(patch.id)["alert_triggered"] is True


def test_failed_timeline_is_not_reclaimed_during_cooldown(store):
    patch = store.create_patch(10.0, 10.0, None)
    store.created_patches.append(patch.id)
    claimed = store.claim_timeline(patch.id, 1)
    store.fail_timeline(claimed.id, "boom")
    assert store.claim_timeline(patch.id, 1) is None
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE timelines SET updated_at = now() - interval '1 hour' WHERE id = %s",
            (claimed.id,),
        )
    assert store.claim_timeline(patch.id, 1).status == "building"


def test_dequeue_takes_a_queued_timeline_once(store):
    patch = store.create_patch(222.222, -22.0, None)
    store.created_patches.append(patch.id)
    assert store.claim_timeline(patch.id, 3) is not None

    dequeued = store.dequeue_timeline()
    assert dequeued is not None and dequeued[0].id == patch.id
    assert dequeued[1].detector == 3 and store.get_timeline(patch.id, 3).stage == "querying"
    again = store.dequeue_timeline()  # Other queued rows may exist, but not this one.
    assert again is None or again[0].id != patch.id


def test_patch_crossmatch_saves_json(store):
    # Used to raise NameError (Jsonb was never imported in this method).
    patch = store.create_patch(201.234, -12.5, None)
    store.created_patches.append(patch.id)
    store.save_patch_crossmatch(patch.id, {"n": 3, "g_complete": float("nan")}, None)
