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
    plan_progressive_waves,
    select_evenly,
    split_into_epochs,
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


def test_short_passes_stay_whole_even_with_few_frames():
    # A pass is the only image of its date, so a short one is kept although it has few frames.
    assert split_into_epochs([0, 1, 2, 200, 201, 400]) == [[0, 1, 2], [3, 4], [5]]
    assert split_into_epochs([]) == []


def test_long_passes_are_cut_and_small_spans_folded_into_a_neighbour():
    mjds = [2.0 * i for i in range(30)]  # One pass of 58 days, a frame every 2 days.
    epochs = split_into_epochs(mjds, gap_days=30, max_span_days=14, min_frames=6)
    # Spans of 14 days hold 7 frames; the last one (2 frames) joins the span before it.
    assert [len(e) for e in epochs] == [7, 7, 7, 9]
    assert [i for e in epochs for i in e] == list(range(30))
    # With a higher minimum the spans keep merging until each one is big enough.
    assert [len(e) for e in split_into_epochs(mjds, 30, 14, 12)] == [14, 16]


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

    stored = [image for _, image in store.images.values()]
    # One stretch for all sizes; the float32 data is kept for the largest size only.
    assert len({(i.display_min, i.display_max) for i in stored}) == 1
    for image in stored:
        assert (image.npz is not None) == (image.size == "large")
        if image.npz:
            data = np.load(io.BytesIO(image.npz))
            assert data["image"].dtype == np.float32
            assert data["image"].shape == data["variance"].shape == (image.height_px,) * 2

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


def test_rebuild_replaces_a_ready_timeline_with_fresh_frames():
    records = make_records([60914.0, 61110.0])
    service, store = make_service(records)
    patch = service.resolve_patch(target_slug="barnards-star")
    first = service.build_now(patch, 3)
    assert first is not None and len(store.list_images(first.id, "medium")) == 2

    service._query_frames = lambda *args: make_records([60914.0, 61110.0, 61300.0])
    rebuilt = service.rebuild_now(patch, 3)
    assert rebuilt is not None and rebuilt.status == "ready" and rebuilt.id == first.id
    assert len(store.list_images(rebuilt.id, "medium")) == 3
    # Exposure rows describe the new build only.
    assert len(store.list_nasa_sector_exposures(patch.id, detector=3)) == 3


def test_failed_rebuild_keeps_the_old_images():
    service, store = make_service(make_records([60914.0, 61110.0]))
    patch = service.resolve_patch(target_slug="barnards-star")
    timeline = service.build_now(patch, 3)
    assert timeline is not None
    before = [i.id for i in store.list_images(timeline.id, "medium")]

    def down(*args):
        raise RuntimeError("IRSA down")

    service._query_frames = down
    with pytest.raises(RuntimeError):
        service.rebuild_now(patch, 3)
    after = store.get_timeline(patch.id, 3)
    assert after is not None and after.status == "ready"
    assert [i.id for i in store.list_images(timeline.id, "medium")] == before


def test_plan_progressive_waves_orders_first_light_then_breadth_first():
    waves = plan_progressive_waves([[0, 1, 2], [3, 4, 5], [6, 7, 8]], limit=3)
    assert waves[0] == ("first_light", [(0, 0)])
    assert waves[1] == ("preview_ready", [(1, 3), (2, 6)])
    assert waves[2] == ("refining", [(0, 1), (1, 4), (2, 7)])
    assert waves[3] == ("refining", [(0, 2), (1, 5), (2, 8)])


def test_coordinate_search_renders_partial_images_progressively_while_building():
    records = make_records([60914.0, 60915.0, 61110.0, 61111.0, 61300.0, 61301.0])
    release_wave1 = threading.Event()
    release_wave2 = threading.Event()
    wave1_uris = {records[2].uri, records[4].uri}
    wave2_uris = {records[1].uri, records[3].uri, records[5].uri}

    def gated_fetch(uri, ra, dec, size):
        if uri in wave1_uris:
            release_wave1.wait(10)
        elif uri in wave2_uris:
            release_wave2.wait(10)
        return make_cutout_bytes(ra, dec, shape=(211, 211))

    service, store = make_service(records, fetch=gated_fetch)
    patch = service.resolve_patch(ra=RA, dec=DEC)
    initial = service.timeline(patch, 3, "medium")
    assert initial.status == "building"

    deadline = time.monotonic() + 10.0
    view = initial
    while time.monotonic() < deadline:
        view = service.timeline(patch, 3, "medium")
        if view.timeline.stage == "first_light":
            break
        time.sleep(0.02)

    assert view.status == "building" and view.timeline.stage == "first_light"
    assert len(view.images) == 1
    assert view.images[0].epoch_index == 0 and view.images[0].frames_used == 1
    png_bytes = store.get_png(view.images[0].id)
    assert png_bytes is not None and Image.open(io.BytesIO(png_bytes)).size == (59, 59)

    release_wave1.set()
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        view = service.timeline(patch, 3, "medium")
        if view.timeline.stage == "preview_ready":
            break
        time.sleep(0.02)

    assert view.status == "building" and view.timeline.stage == "preview_ready"
    assert [img.epoch_index for img in view.images] == [0, 1, 2]
    assert [img.frames_used for img in view.images] == [1, 1, 1]

    release_wave2.set()
    final = wait_until_settled(service, patch)
    assert final.status == "ready"
    assert [img.epoch_index for img in final.images] == [0, 1, 2]
    assert [img.frames_used for img in final.images] == [2, 2, 2]
    assert final.timeline.frames_found == 6 and final.timeline.frames_used == 6


def test_featured_object_build_does_not_use_partial_waves():
    records = make_records([60914.0, 60915.0, 61110.0, 61111.0])
    release = threading.Event()
    first_done = threading.Event()

    def gated_fetch(uri, ra, dec, size):
        if uri == records[0].uri:
            first_done.set()
            return make_cutout_bytes(ra, dec, shape=(211, 211))
        release.wait(10)
        return make_cutout_bytes(ra, dec, shape=(211, 211))

    service, _ = make_service(records, fetch=gated_fetch)
    patch = service.resolve_patch(target_slug="barnards-star")
    service.timeline(patch, 3, "medium")
    assert first_done.wait(5)
    time.sleep(0.1)

    mid = service.timeline(patch, 3, "medium")
    assert mid.status == "building"
    assert mid.timeline.stage == "downloading"
    assert mid.images == []

    release.set()
    final = wait_until_settled(service, patch)
    assert final.status == "ready" and len(final.images) == 2


# ----- per-exposure quick-look photometry -------------------------------------------------

from app.irsa import FrameRecord  # noqa: E402
from app.service import _build_exposure_row  # noqa: E402
from app.store import Patch, Timeline  # noqa: E402


def _row(source_position=None, flag_value_at_star=0):
    patch = Patch(1, RA, DEC, "barnards-star")
    timeline = Timeline(1, 1, 3, "building", "downloading", 0, 0, None, None, None, None)
    record = FrameRecord("ibe/data/spherex/qr3/level2/x/3/x_D3.fits", 61000.0, 61000.1)
    data = make_cutout_bytes(
        RA, DEC, star_offset_px=(0, 3), shape=(31, 31), flag_value_at_star=flag_value_at_star
    )
    cutout = imaging.read_cutout(data, RA, DEC)
    return _build_exposure_row(patch, timeline, 0, record, cutout, data, source_position)


def _star_position():
    # The fake star is 3 pixels north of the patch centre.
    return RA, DEC + 3 * 6.15 / 3600


def test_exposure_photometry_follows_the_moving_source():
    at_centre = _row()
    at_source = _row(source_position=_star_position())
    assert at_source["aperture_flux_ujy"] > 10 * at_centre["aperture_flux_ujy"]
    assert round(at_source["target_pix_y"]) == round(at_centre["target_pix_y"]) + 3


def test_exposure_photometry_is_skipped_when_the_aperture_is_saturated():
    row = _row(source_position=_star_position(), flag_value_at_star=1 << 26)  # BLOOM
    assert row["aperture_flux_ujy"] is None
    assert row["aperture_sigma_reported_ujy"] is None
