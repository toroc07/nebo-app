import io
import threading
import time

import numpy as np
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

# A free field 1 deg east of Barnard's Star: coordinate searches here must not match a catalogue object.
RA, DEC = 270.446223, 4.76878


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


def test_typed_j2000_coordinates_of_a_moving_target_open_its_patch(client):
    # WISE 0855 as SIMBAD gives it (J2000): 128" from its 2026.2 position, outside the 30" reuse radius.
    http, _ = client
    by_target = http.get("/api/v1/timeline", params={"target": "wise-0855", "detector": 6}).json()
    typed = http.get("/api/v1/timeline", params={"ra": 133.79512, "dec": -7.24514, "detector": 6}).json()
    assert typed["patch"]["target"] == "wise-0855"
    assert typed["patch"]["id"] == by_target["patch"]["id"]
    far = http.get("/api/v1/timeline", params={"ra": 10.0, "dec": 10.0, "detector": 6}).json()
    assert far["patch"]["target"] is None


def test_targets_and_patches(client):
    http, _ = client
    targets = http.get("/api/v1/targets").json()
    assert {t["slug"] for t in targets} >= {"barnards-star", "wise-0855"}
    assert http.get("/api/v1/patches").json() == []


def test_retry_after_is_short_only_in_early_stages():
    from app.main import retry_after_for

    assert retry_after_for("querying") == 2 and retry_after_for("first_light") == 2
    assert retry_after_for("refining") == 5 and retry_after_for(None) == 5


def test_timeline_202_then_200_with_images(client):
    http, service = client
    params = {"ra": RA, "dec": DEC, "size": "small", "detector": 3}

    first = http.get("/api/v1/timeline", params=params)
    assert first.status_code == 202
    assert first.headers["Retry-After"] == "2"  # early stage: poll fast
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
        assert {"span_days", "max_gap_days", "mixed_bursts", "wavelength_um"} <= set(epoch["coverage"])
        quality = epoch["quality"]
        assert quality["frames_used"] == epoch["frames_used"]
        assert quality["frames_available"] == epoch["frames_available"]
        assert 0.0 <= quality["clean_fraction"] <= 1.0
        assert quality["clean_fraction"] + quality["flagged_fraction"] == pytest.approx(1.0, abs=1e-3)
        assert isinstance(epoch["warnings"], list)
        assert all({"code", "text"} <= set(w) for w in epoch["warnings"])
        assert epoch["mask_url"].endswith("/mask.png?size=medium")
        position = epoch["expected_position"]
        assert position["in_image"] and 0 <= position["x"] <= body["size"]["width_px"] - 1
    # Barnard moves north between the two epochs (dec grows, PNG y shrinks).
    first, last = (e["expected_position"] for e in body["epochs"])
    assert last["dec"] > first["dec"] and last["y"] < first["y"]


def test_timeline_reports_galactic_and_ecliptic_latitude(client):
    http, service = client
    params = {"target": "barnards-star", "size": "small", "detector": 3}
    http.get("/api/v1/timeline", params=params)
    wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"))
    body = http.get("/api/v1/timeline", params=params).json()
    # Barnard's Star: l = 31.0 deg, b = +14.1 deg; ecliptic latitude about +28 deg.
    assert body["galactic_b"] == pytest.approx(14.06, abs=0.05)
    assert body["ecliptic_beta"] == pytest.approx(28.0, abs=0.5)
    # Out of the plane: no dense-field warning. The fake archive has 1 frame per epoch.
    for epoch in body["epochs"]:
        assert [w["code"] for w in epoch["warnings"]] == ["few_frames"]
        assert epoch["quality"]["frames_used"] == 1


def test_epoch_mask_png(client):
    http, service = client
    # A cutout smaller than the large patch leaves its edges without data.
    service._fetch_cutout = lambda uri, ra, dec, size: make_cutout_bytes(ra, dec, shape=(101, 101))
    params = {"ra": RA, "dec": DEC, "size": "large", "detector": 3}
    http.get("/api/v1/timeline", params=params)
    wait_until_settled(service, service.resolve_patch(ra=RA, dec=DEC))
    body = http.get("/api/v1/timeline", params=params).json()
    epoch = body["epochs"][0]

    mask = http.get(epoch["mask_url"])
    assert mask.status_code == 200 and mask.headers["content-type"] == "image/png"
    assert "immutable" in mask.headers["cache-control"]
    pixels = np.asarray(Image.open(io.BytesIO(mask.content)).convert("RGBA"))
    side = body["size"]["width_px"]
    assert pixels.shape == (side, side, 4)
    # Masked exactly where the float data is NaN (PNG rows are flipped: north up).
    data = np.load(io.BytesIO(http.get(epoch["npz_url"]).content))["image"]
    assert np.array_equal(pixels[..., 3] > 0, np.flipud(~np.isfinite(data)))
    fraction = float(mask.headers["x-masked-fraction"])
    assert 0.0 < fraction < 1.0 and fraction == pytest.approx((~np.isfinite(data)).mean(), abs=1e-4)
    assert pixels[side // 2, side // 2, 3] == 0, "the covered centre is not masked"

    # Smaller sizes point at the same float image, cropped to their own grid.
    small = http.get("/api/v1/timeline", params=params | {"size": "small"}).json()
    assert small["epochs"][0]["mask_url"] == epoch["mask_url"].replace("size=large", "size=small")
    small_mask = Image.open(io.BytesIO(http.get(small["epochs"][0]["mask_url"]).content))
    assert small_mask.size == (small["size"]["width_px"],) * 2
    assert http.get("/api/v1/images/999/mask.png").status_code == 404


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

    # The early answer tells the client to ask again; without wait_for it stays 202, because the
    # web client treats any 200 as final.
    assert early.headers["Retry-After"]
    assert http.get("/api/v1/timeline", params=params).status_code == 202

    release_rest.set()
    wait_until_settled(service, service.resolve_patch(ra=RA, dec=DEC), size="small")
    final = http.get("/api/v1/timeline", params=params)
    assert final.status_code == 200
    final_body = final.json()
    assert len(final_body["epochs"]) == 2
    assert final_body["frames_found"] == 4 and final_body["frames_used"] == 4
    assert all(e["frames_used"] == 2 for e in final_body["epochs"])


def test_featured_object_ignores_early_ready(client):
    http, service = client
    records = make_records([60914.0, 61110.0])
    release = threading.Event()
    service._query_frames = lambda *args: records
    service._fetch_cutout = lambda uri, ra, dec, size: (
        release.wait(10) or make_cutout_bytes(ra, dec, shape=(211, 211))
    )
    resp = http.get("/api/v1/timeline", params={"target": "barnards-star", "wait_for": "first_light"})
    assert resp.status_code == 202
    assert resp.json()["epochs"] == []
    release.set()
    wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"))


def test_startup_without_database_does_not_crash(monkeypatch):
    from app import config as cfg

    monkeypatch.setattr(cfg, "DATABASE_URL", "")
    with TestClient(app):  # runs the lifespan warm-up
        pass


def test_timeline_rgb_reports_missing_detectors_and_renders_when_ready(client):
    http, service = client
    records = make_records([60914.0])
    service._query_frames = lambda *args: records
    service._fetch_cutout = lambda uri, ra, dec, size: make_cutout_bytes(ra, dec, shape=(211, 211))

    # Build only detector 3 first; R=6, G=3, B=1 should report missing [1, 6].
    assert http.get("/api/v1/timeline", params={"target": "barnards-star", "detector": 3}).status_code == 202
    wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"))
    missing = http.get("/api/v1/timeline/rgb", params={"target": "barnards-star", "r": 6, "g": 3, "b": 1})
    assert missing.status_code == 404
    assert missing.json()["detail"]["missing_detectors"] == [1, 6]

    # Build detectors 1 and 6 as well; RGB composite should now return an RGBA PNG.
    for det in (1, 6):
        http.get("/api/v1/timeline", params={"target": "barnards-star", "detector": det})
        wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"), detector=det)
    rgb = http.get("/api/v1/timeline/rgb", params={"target": "barnards-star", "r": 6, "g": 3, "b": 1, "size": "small"})
    assert rgb.status_code == 200
    assert rgb.headers["content-type"] == "image/png"
    assert rgb.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_spectrum_channels_follow_the_catalog_and_keep_blankch_null():
    from app.main import spectrum_channels

    flux = [float(i) for i in range(102)]
    channels = spectrum_channels(
        {"flux_mjy": flux, "sigma_reported_mjy": [0.1] * 102, "valid_mask": [True] * 101 + [False]}
    )
    assert len(channels) == 102
    assert channels[0] == {
        "channel_id": 1, "band": 1, "lambda_c_um": channels[0]["lambda_c_um"],
        "flux_mjy": 0.0, "sigma_mjy": 0.1, "is_blankch": False,
    }
    blank = [c for c in channels if c["is_blankch"]]
    assert [c["channel_id"] for c in blank] == [51, 52]
    assert all(c["flux_mjy"] is None for c in blank)
    assert channels[-1]["flux_mjy"] is None  # Invalid channel: null, never 0.
