import pytest
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
