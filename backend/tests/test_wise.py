import pytest
import requests

from app import gaia, wise
from tests.test_api import DEC, RA, client  # noqa: F811

WISE_CSV = """source_id,ra,dec,pmra,pmdec,w1mpro,w2mpro,w1sigmpro,w2sigmpro
0855m0714,133.782,-7.244,-8123.7,673.2,17.45,13.89,0.12,0.03
bg1,133.790,-7.250,2.0,-1.5,14.10,14.05,0.02,0.03
,1.0,2.0,0,0,10,10,0.1,0.1
"""


class FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def test_wise_parse_csv_and_color():
    sources = wise.parse_csv(WISE_CSV)
    assert [s.source_id for s in sources] == ["0855m0714", "bg1"]
    bd, bg = sources
    assert bd.w1_w2_color == pytest.approx(3.56, abs=1e-3)
    assert bd.pm_total_mas_yr == pytest.approx(8151.5, abs=0.5)
    assert bg.w1_w2_color == pytest.approx(0.05, abs=1e-3)


def test_wise_query_cone_retries_then_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(wise.time, "sleep", lambda s: None)

    def fake_post(url, data, timeout):
        calls.append(data["QUERY"])
        return FakeResponse(503)

    monkeypatch.setattr(wise.requests, "post", fake_post)
    with pytest.raises(wise.WiseQueryError):
        wise.query_cone(RA, DEC, 0.2)
    assert len(calls) == wise.QUERY_ATTEMPTS
    assert "catwise_2020" in calls[0]



def test_wise_query_cone_rejects_non_csv_answer(monkeypatch):
    monkeypatch.setattr(wise.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        wise.requests, "post", lambda url, data, timeout: FakeResponse(200, "<html>Proxy Error</html>")
    )
    with pytest.raises(wise.WiseQueryError):
        wise.query_cone(RA, DEC, 0.2)


def test_wise_query_cone_accepts_header_only_answer(monkeypatch):
    header = WISE_CSV.splitlines()[0] + "\n"
    monkeypatch.setattr(wise.requests, "post", lambda url, data, timeout: FakeResponse(200, header))
    assert wise.query_cone(RA, DEC, 0.2) == []

def test_wise_endpoint_crossmatches_gaia_and_flags_cold_candidate(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    wise_calls = []

    def fake_wise(ra, dec, radius_deg, w2_max=wise.DEFAULT_W2_MAX, limit=wise.MAX_ROWS):
        wise_calls.append((ra, dec))
        return [
            wise.WiseSource("cold_bd", RA, DEC, 0.0, 0.0, 17.5, 13.9, 0.1, 0.03),
            wise.WiseSource("known_star", RA + 0.01, DEC + 0.01, 0.0, 0.0, 12.0, 11.9, 0.02, 0.02),
        ]

    def fake_gaia(ra, dec, radius_deg, g_max=gaia.DEFAULT_G_MAX, limit=gaia.MAX_ROWS):
        return [
            gaia.GaiaSource("g1", RA + 0.01, DEC + 0.01, 0.0, 0.0, 1.0, 13.0, 1.2),
        ]

    monkeypatch.setattr(wise, "query_cone", fake_wise)
    monkeypatch.setattr(gaia, "query_cone", fake_gaia)

    params = {"size": "medium", "mjd": [61000.0, 61180.0]}
    r1 = http.get(f"/api/v1/patches/{patch.id}/wise", params=params)
    assert r1.status_code == 200
    body = r1.json()
    assert body["catalog"]["name"] == "CatWISE2020"
    assert body["catalog"]["gaia_crossmatched"] is True

    by_id = {s["source_id"]: s for s in body["sources"]}
    assert by_id["cold_bd"]["cold_candidate"] is True
    assert by_id["cold_bd"]["gaia_match"] is None
    assert by_id["known_star"]["cold_candidate"] is False
    assert by_id["known_star"]["gaia_match"]["source_id"] == "g1"

    # Second call should hit api_query_cache
    r2 = http.get(f"/api/v1/patches/{patch.id}/wise", params=params)
    assert r2.status_code == 200
    assert len(wise_calls) == 1


def test_wise_endpoint_returns_502_when_irsa_unavailable(client, monkeypatch):  # noqa: F811
    http, service = client
    patch = service.resolve_patch(ra=RA, dec=DEC)

    def fail_wise(*args, **kwargs):
        raise wise.WiseQueryError("down")

    monkeypatch.setattr(wise, "query_cone", fail_wise)
    r = http.get(f"/api/v1/patches/{patch.id}/wise", params={"mjd": [61000.0]})
    assert r.status_code == 502
    assert r.json()["code"] == "wise_unavailable"
