import io
import threading
import time

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import db
from app.main import app, get_service, get_store
from app.service import ServiceBusy, TimelineService
from app.targets import TARGETS
from tests.fakes import make_cutout_bytes, make_records
from tests.memory_store import MemoryStore
from tests.test_service import wait_until_settled

RA, DEC = 269.446223, 4.76878


@pytest.fixture
def client():
    store = MemoryStore()
    store.upsert_targets(TARGETS)
    service = TimelineService(
        store,
        query_frames=lambda *args: make_records([60914.0, 61110.0]),
        fetch_cutout=lambda uri, ra, dec, size: make_cutout_bytes(ra, dec, shape=(211, 211)),
    )
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_service] = lambda: service
    yield TestClient(app), service
    app.dependency_overrides.clear()


def test_targets_and_patches(client):
    http, _ = client
    targets = http.get("/api/v1/targets").json()
    assert {t["slug"] for t in targets} >= {"barnards-star", "wise-0855"}
    assert http.get("/api/v1/patches").json() == []


def test_timeline_202_then_200_with_images(client):
    http, service = client
    params = {"ra": RA, "dec": DEC, "size": "small", "detector": 3}

    first = http.get("/api/v1/timeline", params=params)
    assert first.status_code == 202
    assert first.headers["Retry-After"] == "5"
    body = first.json()
    assert body["status"] == "building" and body["detector"]["bandpass"] == "SPHEREx-D3"

    patch = service.resolve_patch(ra=RA, dec=DEC)
    wait_until_settled(service, patch)
    ready = http.get("/api/v1/timeline", params=params)
    assert ready.status_code == 200
    body = ready.json()
    assert body["size"]["name"] == "small" and body["size"]["width_px"] % 2 == 1
    assert body["orientation"] == "north_up_east_left"
    assert len(body["epochs"]) == 2

    image = http.get(body["epochs"][0]["image_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert "immutable" in image.headers["cache-control"]

    # Changing the size is served from the same build.
    assert http.get("/api/v1/timeline", params=params | {"size": "large"}).status_code == 200
    assert http.get("/api/v1/patches").json()[0]["detectors_ready"] == [3]


def test_timeline_by_target_uses_its_recommended_detector(client):
    http, _ = client
    body = http.get("/api/v1/timeline", params={"target": "wise-0855"}).json()
    assert body["patch"]["target"] == "wise-0855"
    assert body["detector"]["id"] == 6


@pytest.mark.parametrize(
    "params",
    [
        {"ra": 400, "dec": 0},
        {"ra": 10, "dec": 0, "detector": 7},
        {"ra": 10, "dec": 0, "size": "huge"},
        {"ra": 10},
        {"target": "wise-0855", "ra": 10, "dec": 0},
        {"target": "Bad Slug!"},
    ],
)
def test_timeline_validates_parameters(client, params):
    http, _ = client
    assert http.get("/api/v1/timeline", params=params).status_code == 422


def test_unknown_target_and_image(client):
    http, _ = client
    assert http.get("/api/v1/timeline", params={"target": "nope"}).status_code == 404
    assert http.get("/api/v1/images/999.png").status_code == 404
    assert http.get("/api/v1/images/0.png").status_code == 422


def test_busy_service_answers_503_with_retry_after(client, monkeypatch):
    http, service = client
    monkeypatch.setattr(service, "timeline", lambda *args: (_ for _ in ()).throw(ServiceBusy()))
    response = http.get("/api/v1/timeline", params={"ra": 10.0, "dec": 20.0})
    assert response.status_code == 503
    assert response.json()["code"] == "busy" and response.headers["Retry-After"] == "30"


def test_without_database_the_api_answers_503(monkeypatch):
    monkeypatch.setattr(db.config, "DATABASE_URL", "")
    http = TestClient(app)
    assert http.get("/api/v1/health").json() == {"status": "ok", "database": "not_configured"}
    response = http.get("/api/v1/timeline", params={"target": "wise-0855"})
    assert response.status_code == 503
    assert response.json()["code"] == "database_not_configured"


def test_timeline_has_corners_data_version_and_expected_position(client):
    http, service = client
    params = {"target": "barnards-star", "size": "medium", "detector": 3}
    http.get("/api/v1/timeline", params=params)
    wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"))
    body = http.get("/api/v1/timeline", params=params).json()

    assert set(body["sector"]["corners"]) == {"NW", "NE", "SE", "SW"}
    assert body["sector"]["center"]["ra"] == pytest.approx(269.446223)
    assert body["data"]["source"] and body["data"]["processed_at"]
    for epoch in body["epochs"]:
        assert epoch["releases"], "every epoch names the data release of its exposures"
        position = epoch["expected_position"]
        assert position["in_image"] and 0 <= position["x"] <= body["size"]["width_px"] - 1
    # Barnard moves north between the two epochs (dec grows, PNG y shrinks).
    first, last = (e["expected_position"] for e in body["epochs"])
    assert last["dec"] > first["dec"] and last["y"] < first["y"]


def test_expected_position_is_null_without_catalogue_target(client):
    http, service = client
    params = {"ra": RA, "dec": DEC, "size": "small", "detector": 3}
    http.get("/api/v1/timeline", params=params)
    wait_until_settled(service, service.resolve_patch(ra=RA, dec=DEC))
    epochs = http.get("/api/v1/timeline", params=params).json()["epochs"]
    assert all(e["expected_position"] is None for e in epochs)


def test_timeline_diff(client):
    http, service = client
    params = {"ra": RA, "dec": DEC, "size": "small", "detector": 3}
    assert http.get("/api/v1/timeline/diff", params=params | {"a": 0, "b": 1}).status_code == 404
    http.get("/api/v1/timeline", params=params)
    wait_until_settled(service, service.resolve_patch(ra=RA, dec=DEC))

    diff = http.get("/api/v1/timeline/diff", params=params | {"a": 0, "b": 1})
    assert diff.status_code == 200 and diff.headers["content-type"] == "image/png"
    assert float(diff.headers["x-diff-limit"]) > 0
    side = http.get("/api/v1/timeline", params=params).json()["size"]["width_px"]
    assert Image.open(io.BytesIO(diff.content)).size == (side, side)
    assert http.get("/api/v1/timeline/diff", params=params | {"a": 0, "b": 9}).status_code == 404


def test_coordinate_timeline_202_includes_first_light_static_image_and_sector(client, monkeypatch):
    from app import config

    http, service = client
    records = make_records([60914.0, 60915.0, 61110.0, 61111.0])
    release_rest = threading.Event()

    def gated_fetch(uri, ra, dec, size):
        if uri != records[0].uri:
            release_rest.wait(10)
        return make_cutout_bytes(ra, dec, shape=(211, 211))

    service._query_frames = lambda *args: records
    service._fetch_cutout = gated_fetch
    params = {"ra": RA, "dec": DEC, "size": "small", "detector": 3}

    first = http.get("/api/v1/timeline", params=params)
    assert first.status_code == 202
    first_body = first.json()
    assert set(first_body["sector"]["corners"]) == {"NW", "NE", "SE", "SW"}
    assert first_body["size"]["name"] == "small"

    deadline = time.monotonic() + 10.0
    partial_resp = first
    while time.monotonic() < deadline:
        partial_resp = http.get("/api/v1/timeline", params=params)
        if partial_resp.json()["progress"]["stage"] == "first_light":
            break
        time.sleep(0.02)

    assert partial_resp.status_code == 202
    partial = partial_resp.json()
    assert partial["is_partial"] is True
    assert partial["progress"]["stage"] == "first_light"
    assert partial["progress"]["epochs_ready"] == 1
    assert partial["preview_image_url"].startswith("/api/v1/images/")
    assert len(partial["epochs"]) == 1 and partial["epochs"][0]["frames_used"] == 1

    img_resp = http.get(partial["preview_image_url"])
    assert img_resp.status_code == 200 and img_resp.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(img_resp.content)).size == (31, 31)

    # Optional early-ready mode returns 200 as soon as the static first-light image exists.
    early = http.get("/api/v1/timeline", params=params | {"wait_for": "first_light"})
    assert early.status_code == 200
    early_body = early.json()
    assert early_body["status"] == "ready"
    assert early_body["is_partial"] is True and early_body["refining"] is True
    assert early_body["data"]["source"]
    assert len(early_body["epochs"]) == 1

    # Waiting for full preview stays 202 while only epoch 0 has landed.
    assert http.get("/api/v1/timeline", params=params | {"wait_for": "preview"}).status_code == 202

    # Env flag enables early-ready 200 for coordinate searches without changing Featured Objects.
    monkeypatch.setattr(config, "PROGRESSIVE_EARLY_READY", True)
    assert http.get("/api/v1/timeline", params=params).status_code == 200

    release_rest.set()
    wait_until_settled(service, service.resolve_patch(ra=RA, dec=DEC), size="small")
    final = http.get("/api/v1/timeline", params=params)
    assert final.status_code == 200
    final_body = final.json()
    assert len(final_body["epochs"]) == 2
    assert final_body["frames_found"] == 4 and final_body["frames_used"] == 4
    assert all(e["frames_used"] == 2 for e in final_body["epochs"])


def test_featured_object_ignores_early_ready_toggle(client, monkeypatch):
    from app import config

    http, service = client
    records = make_records([60914.0, 61110.0])
    release = threading.Event()
    service._query_frames = lambda *args: records
    service._fetch_cutout = lambda uri, ra, dec, size: (
        release.wait(10) or make_cutout_bytes(ra, dec, shape=(211, 211))
    )
    monkeypatch.setattr(config, "PROGRESSIVE_EARLY_READY", True)
    resp = http.get("/api/v1/timeline", params={"target": "barnards-star", "wait_for": "first_light"})
    assert resp.status_code == 202
    assert resp.json()["epochs"] == []
    release.set()
    wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"))
