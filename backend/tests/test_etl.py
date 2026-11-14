import threading
import time

import pytest

from app import config, etl
from tests.fakes import make_records
from tests.test_service import DEC, RA, make_service

RECORDS = make_records([60914.0, 61110.0])


def test_parse_coords_accepts_both_separators_and_comments():
    assert etl.parse_coords("10,20; 30.5,-40 # note\n\n359.9,90") == [
        (10.0, 20.0),
        (30.5, -40.0),
        (359.9, 90.0),
    ]


@pytest.mark.parametrize("text", ["360,0", "10,91", "10,-90.5", "10"])
def test_parse_coords_rejects_bad_values(text):
    with pytest.raises(ValueError):
        etl.parse_coords(text)


def test_queue_mode_api_only_queues_and_a_worker_builds(monkeypatch):
    monkeypatch.setattr(config, "BUILD_MODE", "queue")
    service, store = make_service(RECORDS)
    patch = service.resolve_patch(ra=RA, dec=DEC)

    assert service.timeline(patch, 3, "medium").status == "building"
    time.sleep(0.3)  # An inline build would have progressed by now.
    assert store.get_timeline(patch.id, 3).stage == "queued"
    assert service.timeline(patch, 3, "medium").status == "building"  # Not queued twice.

    stop = threading.Event()
    etl.run_worker(service, once=True, poll_s=0.01, stop=stop)

    view = service.timeline(patch, 3, "medium")
    assert view.status == "ready" and len(view.images) == 2
    assert service.work_one() is False  # Queue is empty now.


def test_run_batch_builds_targets_and_free_coordinates():
    service, store = make_service(RECORDS)
    failures = etl.run_batch(service, ["barnards-star"], [(10.0, 20.0)], [3])
    assert failures == 0
    assert {t.status for t in store.timelines.values()} == {"ready"}
    assert len(store.timelines) == 2


def test_run_batch_counts_fields_without_data():
    service, _ = make_service([])
    assert etl.run_batch(service, [], [(10.0, 20.0)], [3]) == 1
