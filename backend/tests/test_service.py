import io
import threading
import time

import numpy as np
import pytest
from PIL import Image

from app import config, imaging
from app.service import (
    ServiceBusy,
    TargetNotFound,
    TimelineService,
    group_into_epochs,
    select_evenly,
)
from app.targets import TARGETS
from tests.fakes import make_cutout_bytes, make_records
from tests.memory_store import MemoryStore

RA, DEC = 269.446223, 4.768780


def wait_until_settled(service: TimelineService, patch, detector=3, size="medium", timeout_s=30.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        view = service.timeline(patch, detector, size)
        if view.status != "building":
            return view
        time.sleep(0.05)
    raise AssertionError("Build did not finish in time")


def make_service(records, fetch=None) -> tuple[TimelineService, MemoryStore]:
    store = MemoryStore()
    store.upsert_targets(TARGETS)
    service = TimelineService(
        store,
        query_frames=lambda ra, dec, detector: records,
        fetch_cutout=fetch or (lambda uri, ra, dec, size: make_cutout_bytes(ra, dec, shape=(211, 211))),
    )
    return service, store


def test_group_into_epochs_splits_on_large_gaps():
    assert group_into_epochs([0, 1, 2, 200, 201, 400]) == [[0, 1, 2], [3, 4], [5]]
    assert group_into_epochs([]) == []


def test_select_evenly_keeps_first_and_last():
    assert select_evenly(list(range(10)), 3) == [0, 4, 9]
    assert select_evenly([7, 8], 5) == [7, 8]


def test_patches_are_reused_within_the_match_radius():
    service, store = make_service([])
    first = service.resolve_patch(ra=RA, dec=DEC)
    near = service.resolve_patch(ra=RA, dec=DEC + 10 / 3600)  # 10 arcsec away
    far = service.resolve_patch(ra=RA, dec=DEC + 60 / 3600)  # 1 arcmin away
    assert near.id == first.id and far.id != first.id

    by_target = service.resolve_patch(target_slug="wise-0855")
    assert by_target.target_slug == "wise-0855"
    assert service.resolve_patch(target_slug="wise-0855").id == by_target.id
    with pytest.raises(TargetNotFound):
        service.resolve_patch(target_slug="nope")


def test_build_stores_one_image_per_epoch_and_size():
    records = make_records([60914.0, 60915.0, 60916.0, 61110.0, 61111.0])
    service, store = make_service(records)
    patch = service.resolve_patch(ra=RA, dec=DEC)

    first = service.timeline(patch, 3, "medium")
    assert first.status == "building"

    view = wait_until_settled(service, patch)
    assert view.status == "ready"
    assert [image.epoch_index for image in view.images] == [0, 1]
    assert view.timeline.frames_found == 5 and view.timeline.frames_used == 5

    for size, side_deg in config.SIZES_DEG.items():
        images = store.list_images(view.timeline.id, size)
        assert len(images) == 2
        side = imaging.grid_pixels(side_deg)
        png = Image.open(io.BytesIO(store.get_png(images[0].id)))
        assert png.size == (side, side) and images[0].width_px == side
        # Display limits are shared across the epochs of one size.
        assert images[0].display_max == images[1].display_max

    assert store.list_patches_with_data() == [
        {"id": patch.id, "ra": RA, "dec": DEC, "target_slug": None, "detectors_ready": [3]}
    ]


def test_target_stays_on_the_central_pixel_of_every_size():
    records = make_records([60914.0])
    service, store = make_service(records)
    patch = service.resolve_patch(ra=RA, dec=DEC)
    view = wait_until_settled(service, patch)

    for size in config.SIZES_DEG:
        info = store.list_images(view.timeline.id, size)[0]
        grey = np.array(Image.open(io.BytesIO(store.get_png(info.id))))[..., 0]
        y, x = np.unravel_index(np.argmax(grey), grey.shape)
        assert (x, y) == ((info.width_px - 1) // 2, (info.height_px - 1) // 2)


def test_concurrent_requests_start_a_single_build():
    calls = []

    def slow_query(ra, dec, detector):
        calls.append(1)
        time.sleep(0.2)
        return make_records([60914.0])

    service, _ = make_service([])
    service._query_frames = slow_query
    patch = service.resolve_patch(ra=RA, dec=DEC)
    for _ in range(5):
        service.timeline(patch, 3, "small")
    wait_until_settled(service, patch)
    assert len(calls) == 1


def test_no_frames_fails_then_can_be_retried_after_the_cooldown():
    service, store = make_service([])
    patch = service.resolve_patch(ra=RA, dec=DEC)
    view = wait_until_settled(service, patch)
    assert view.status == "failed" and "No SPHEREx images" in view.timeline.error

    # Within the cooldown the failure is reported again, without a new build.
    assert service.timeline(patch, 3, "medium").status == "failed"

    store.age_timeline(view.timeline.id, config.FAILED_RETRY_S + 1)
    assert service.timeline(patch, 3, "medium").status == "building"


def test_stale_build_is_taken_over():
    service, store = make_service(make_records([60914.0]))
    patch = service.resolve_patch(ra=RA, dec=DEC)
    dead = store.claim_timeline(patch.id, 3)  # A build that crashed without reporting.
    assert store.claim_timeline(patch.id, 3) is None

    store.age_timeline(dead.id, config.STALE_BUILD_S + 1)
    assert wait_until_settled(service, patch).status == "ready"


def test_frames_that_fail_to_download_are_skipped():
    records = make_records([60914.0, 60915.0])

    def flaky(uri, ra, dec, size):
        if uri == records[0].uri:
            raise RuntimeError("IRSA timeout")
        return make_cutout_bytes(ra, dec, shape=(211, 211))

    service, _ = make_service(records, fetch=flaky)
    patch = service.resolve_patch(ra=RA, dec=DEC)
    view = wait_until_settled(service, patch)
    assert view.status == "ready"
    assert view.timeline.frames_found == 2 and view.timeline.frames_used == 1


def test_new_builds_are_refused_when_too_many_are_pending(monkeypatch):
    release = threading.Event()

    def blocked_query(ra, dec, detector):
        release.wait(10)
        return make_records([60914.0])

    monkeypatch.setattr(config, "MAX_PENDING_BUILDS", 2)
    service, _ = make_service([])
    service._query_frames = blocked_query
    patches = [service.resolve_patch(ra=RA, dec=dec) for dec in (0.0, 1.0, 2.0)]

    service.timeline(patches[0], 3, "small")
    service.timeline(patches[1], 3, "small")
    with pytest.raises(ServiceBusy):
        service.timeline(patches[2], 3, "small")
    # Asking again for a timeline that is already building is still fine.
    assert service.timeline(patches[0], 3, "small").status == "building"

    release.set()
    for patch in patches[:2]:
        assert wait_until_settled(service, patch, size="small").status == "ready"
    assert service.timeline(patches[2], 3, "small").status == "building"


def test_build_now_skips_ready_timelines():
    calls = []
    records = make_records([60914.0])
    service, _ = make_service(records)
    original = service._query_frames
    service._query_frames = lambda *args: calls.append(1) or original(*args)

    patch = service.resolve_patch(target_slug="barnards-star")
    assert service.build_now(patch, 3).status == "ready"
    assert service.build_now(patch, 3).status == "ready"
    assert len(calls) == 1
