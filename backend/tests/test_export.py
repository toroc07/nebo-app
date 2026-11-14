import json

from PIL import Image

from app import config
from app.export import export
from app.targets import TARGETS
from tests.test_api import client  # noqa: F401  (fixture)
from tests.test_service import wait_until_settled


def test_export_writes_api_shaped_json_and_pngs(client, tmp_path):  # noqa: F811
    http, service = client
    http.get("/api/v1/timeline", params={"target": "barnards-star", "detector": 3})
    wait_until_settled(service, service.resolve_patch(target_slug="barnards-star"))

    skipped = export(
        service.store, tmp_path, ["barnards-star", "wise-0855"], [3], list(config.SIZES_DEG)
    )

    assert skipped == 1  # wise-0855 has no timeline.
    assert len(json.loads((tmp_path / "targets.json").read_text())) == len(TARGETS)
    api = http.get("/api/v1/timeline", params={"target": "barnards-star", "detector": 3}).json()
    body = json.loads((tmp_path / "timeline" / "barnards-star_d3_medium.json").read_text())
    assert body.keys() == api.keys()
    for epoch in body["epochs"]:
        assert not epoch["image_url"].startswith("/")
        assert Image.open(tmp_path / epoch["image_url"]).size[0] == body["size"]["width_px"]
        assert "npz_url" not in epoch
