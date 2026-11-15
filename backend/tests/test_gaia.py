import pytest
import requests

from app import gaia, tap_fallback
from tests.test_api import RA, DEC, client  # noqa: F401  (pytest fixture)

CSV = """source_id,ra,dec,pmra,pmdec,parallax,phot_g_mean_mag,bp_rp
4472832130114786688,269.4485,4.7396,-801.551,10362.394,546.976,8.194,2.835
111,269.45,4.70,,,,17.2,
,1.0,2.0,0,0,0,10,0
"""


class FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def test_parse_csv_keeps_rows_without_proper_motion_and_skips_bad_ones():
    sources = gaia.parse_csv(CSV)
    assert [s.source_id for s in sources] == ["4472832130114786688", "111"]
    barnard, plain = sources
    assert barnard.pm_total_mas_yr == pytest.approx(10393.4, abs=0.5)
    assert barnard.distance_pc == pytest.approx(1.828, abs=1e-3)
    assert not plain.has_proper_motion and plain.pm_total_mas_yr is None
    assert plain.bp_rp is None and plain.distance_pc is None


def test_position_is_unchanged_at_gaia_epoch_and_moves_after():
    barnard = gaia.parse_csv(CSV)[0]
    assert barnard.position_at(gaia.REF_EPOCH_MJD) == (pytest.approx(barnard.ra), pytest.approx(barnard.dec))
    _, dec = barnard.position_at(gaia.REF_EPOCH_MJD + 10 * 365.25)
    assert (dec - barnard.dec) * 3600 == pytest.approx(103.6, abs=0.1)  # ~10.4"/yr north


def test_star_without_proper_motion_stays_put():
    plain = gaia.parse_csv(CSV)[1]
    assert plain.position_at(gaia.REF_EPOCH_MJD + 3650) == (plain.ra, plain.dec)


@pytest.fixture(autouse=True)
def fresh_services():
    tap_fallback.reset()
    yield
    tap_fallback.reset()


def test_query_cone_falls_back_to_gavo_then_remembers_both_down(monkeypatch):
    calls = []

    def fake_post(url, data, timeout):
        calls.append((url, data["QUERY"]))
        return FakeResponse(503)

    monkeypatch.setattr(tap_fallback.requests, "post", fake_post)
    with pytest.raises(gaia.GaiaQueryError):
        gaia.query_cone(RA, DEC, 0.2)
    assert [url for url, _ in calls] == [gaia.TAP_SYNC_URL, gaia.GAVO_TAP_SYNC_URL]
    assert "gaiadr3.gaia_source" in calls[0][1] and "phot_g_mean_mag < 18.00" in calls[0][1]
    assert "gaia.dr3lite" in calls[1][1] and "AS bp_rp" in calls[1][1]
    # Remembered as down: a second request fails at once instead of waiting on both again.
    with pytest.raises(gaia.GaiaQueryError):
        gaia.query_cone(RA, DEC, 0.2)
    assert len(calls) == 2


def test_query_cone_uses_gavo_when_esa_fails(monkeypatch):
    def fake_post(url, data, timeout):
        return FakeResponse(503) if url == gaia.TAP_SYNC_URL else FakeResponse(200, CSV)

    monkeypatch.setattr(tap_fallback.requests, "post", fake_post)
    assert len(gaia.query_cone(RA, DEC, 0.2)) == 2


def test_query_cone_parses_answer(monkeypatch):
    monkeypatch.setattr(tap_fallback.requests, "post", lambda url, data, timeout: FakeResponse(200, CSV))
    assert len(gaia.query_cone(RA, DEC, 0.2)) == 2


def test_nearest_uses_propagated_positions():
    barnard = gaia.parse_csv(CSV)[0]
    mjd = gaia.REF_EPOCH_MJD + 10 * 365.25
    ra, dec = barnard.position_at(mjd)
    match = gaia.nearest(gaia.parse_csv(CSV), ra, dec, mjd)
    assert match is not None and match[0].source_id == barnard.source_id
    assert match[1] == pytest.approx(0.0, abs=1e-6)


# ----- API --------------------------------------------------------------------------------


def _star(source_id: str, ra: float, dec: float, pm=(None, None)) -> gaia.GaiaSource:
    return gaia.GaiaSource(source_id, ra, dec, pm[0], pm[1], 500.0, 9.0, 2.5)


def test_gaia_endpoint_places_stars_per_epoch_and_caches(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    calls = []

    def fake_query(ra, dec, radius_deg, g_max=gaia.DEFAULT_G_MAX, limit=gaia.MAX_ROWS):
        calls.append((ra, dec, radius_deg, g_max))
        return [
            _star("mover", RA, DEC, pm=(0.0, 10000.0)),  # 10"/yr north
            _star("far", RA + 1.0, DEC),  # outside every image
        ]

    monkeypatch.setattr(gaia, "query_cone", fake_query)
    t0 = gaia.REF_EPOCH_MJD
    t1 = t0 + 10 * 365.25
    params = {"size": "medium", "mjd": [t0, t1]}

    body = http.get(f"/api/v1/patches/{patch.id}/gaia", params=params).json()
    assert body["catalog"]["name"] == "Gaia DR3" and body["catalog"]["ref_epoch"] == 2016.0
    assert [s["source_id"] for s in body["stars"]] == ["mover"]
    first, last = body["stars"][0]["positions"]
    side = body["size"]["width_px"]
    assert first["x"] == pytest.approx((side - 1) / 2, abs=0.01)
    assert first["y"] == pytest.approx((side - 1) / 2, abs=0.01)
    # North is up: 100" north is ~16 pixels of 6.15" towards row 0.
    assert first["y"] - last["y"] == pytest.approx(100 / 6.15, abs=0.1)
    assert last["in_image"]

    http.get(f"/api/v1/patches/{patch.id}/gaia", params=params)
    assert len(calls) == 1  # second answer comes from api_query_cache


def test_gaia_endpoint_reports_completeness_limit(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    stars = [
        gaia.GaiaSource("bright", RA, DEC, None, None, None, 9.0, None),
        gaia.GaiaSource("faint", RA, DEC + 0.001, None, None, None, 16.4, None),
    ]
    monkeypatch.setattr(gaia, "query_cone", lambda *a, **k: stars)
    params = {"mjd": [61000.0]}

    full = http.get(f"/api/v1/patches/{patch.id}/gaia", params=params).json()["catalog"]
    assert full["truncated"] is False and full["g_complete"] == 18.0

    # Same patch, lower row limit: a new cache entry, and the list is complete only to G = 16.4.
    monkeypatch.setattr(gaia, "MAX_ROWS", 2)
    cut = http.get(f"/api/v1/patches/{patch.id}/gaia", params=params).json()["catalog"]
    assert cut["truncated"] is True and cut["g_complete"] == 16.4


def test_gaia_endpoint_reports_archive_down(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)

    def down(*args, **kwargs):
        raise gaia.GaiaQueryError("down")

    monkeypatch.setattr(gaia, "query_cone", down)
    response = http.get(f"/api/v1/patches/{patch.id}/gaia", params={"mjd": [61000.0]})
    assert response.status_code == 502 and response.json()["code"] == "gaia_unavailable"


def test_gaia_endpoint_needs_dates_and_known_patch(client):  # noqa: F811
    http, _ = client
    assert http.get("/api/v1/patches/999/gaia", params={"mjd": [61000.0]}).status_code == 404
    assert http.get("/api/v1/patches/1/gaia").status_code == 422
