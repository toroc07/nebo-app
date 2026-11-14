"""PostgresStore against a real database. Skipped unless NEBO_TEST_DATABASE_URL is set.

Use a throwaway database: the tests create the schema and delete the rows they insert.
"""

import os
from datetime import datetime, timezone

import pytest

from app import config
from app.db import SCHEMA_PATH
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
    created: list[int] = []
    pg.created_patches = created
    yield pg
    with pg.pool.connection() as conn:
        conn.execute("DELETE FROM patches WHERE id = ANY(%s)", (created,))
    pg.close()


def _image(epoch: int, size: str) -> EpochImage:
    now = datetime.now(timezone.utc)
    return EpochImage(epoch, size, now, now, 61000.0 + epoch, 8, 6, 31, 31, 0.0, 1.0, b"\x89PNG")


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
    assert any(p["id"] == patch.id for p in store.list_patches_with_data())


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
