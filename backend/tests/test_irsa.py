import pytest
import requests

from app import config, irsa


class FakeResponse:
    def __init__(self, status: int, content: bytes = b"FITS", headers: dict | None = None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


@pytest.fixture
def fake_http(monkeypatch, tmp_path):
    """Queue of responses returned by requests.get; sleeps are recorded, not performed."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    sleeps: list[float] = []
    monkeypatch.setattr(irsa.time, "sleep", sleeps.append)
    queue: list[FakeResponse] = []
    calls: list[str] = []

    def fake_get(url, timeout):
        calls.append(url)
        return queue.pop(0)

    monkeypatch.setattr(irsa.requests, "get", fake_get)
    return queue, calls, sleeps


URI = "ibe/data/spherex/qr3/level2/x/1/level2_x_D1.fits"


def test_retries_503_then_caches(fake_http):
    queue, calls, sleeps = fake_http
    queue += [FakeResponse(503), FakeResponse(503, headers={"Retry-After": "7"}), FakeResponse(200)]

    assert irsa.fetch_cutout(URI, 10.0, 20.0, 0.05) == b"FITS"
    assert len(calls) == 3
    assert sleeps[1] == 7.0  # Retry-After is honoured.

    # Served from the disk cache: no new HTTP call.
    assert irsa.fetch_cutout(URI, 10.0, 20.0, 0.05) == b"FITS"
    assert len(calls) == 3


def test_does_not_retry_404(fake_http):
    queue, calls, _ = fake_http
    queue.append(FakeResponse(404))
    with pytest.raises(RuntimeError, match="Could not download"):
        irsa.fetch_cutout(URI, 10.0, 20.0, 0.05)
    assert len(calls) == 1


def test_gives_up_after_retries(fake_http):
    queue, calls, _ = fake_http
    queue += [FakeResponse(503)] * 3
    with pytest.raises(RuntimeError):
        irsa.fetch_cutout(URI, 10.0, 20.0, 0.05, retries=2)
    assert len(calls) == 3


def test_query_and_urls():
    query = irsa.build_frames_query(269.4462, 4.7688, 6)
    assert "'SPHEREx-D6'" in query and "POINT('ICRS', 269.4462000, 4.7688000)" in query
    with pytest.raises(ValueError):
        irsa.bandpass_name(7)
    assert irsa.cutout_url(URI, 1.0, -2.0, 0.05).endswith("?center=1.0000000,-2.0000000d&size=0.05000")
    assert irsa.FrameRecord(URI, 0.0, 0.0).release == "qr3"


# ----- frame search: TAP with SIA fallback ------------------------------------------------

from astropy.table import Table  # noqa: E402


def _sia_table() -> Table:
    base = "https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2"
    return Table(
        {
            "access_url": [f"{base}/w2/3/b_D3.fits", f"{base}/w1/3/a_D3.fits", f"{base}/w1/6/c_D6.fits"],
            "t_min": [61200.0, 61000.0, 61000.5],
            "t_max": [61200.1, 61000.1, 61000.6],
            "energy_bandpassname": ["SPHEREx-D3", "SPHEREx-D3", "SPHEREx-D6"],
            "dataproduct_subtype": ["science", "science", "science"],
            "s_region": ["POLYGON ICRS 1 2 3 4 5 6"] * 3,
            "em_min": [1.63e-6] * 3,
            "em_max": [2.43e-6] * 3,
            "t_exptime": [113.6] * 3,
        }
    )


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(irsa.time, "sleep", sleeps.append)
    return sleeps


def test_falls_back_to_sia_when_tap_keeps_failing(monkeypatch, no_sleep):
    tap_calls = []

    def broken_tap(query):
        tap_calls.append(query)
        raise RuntimeError("502 Server Error: Proxy Error")

    monkeypatch.setattr(irsa, "_tap_table", broken_tap)
    monkeypatch.setattr(irsa, "_sia_table", lambda ra, dec: _sia_table())

    records = irsa.query_frames(269.4, 4.7, 3)

    assert len(tap_calls) == irsa.TAP_ATTEMPTS and len(no_sleep) == irsa.TAP_ATTEMPTS - 1
    assert [r.mjd_start for r in records] == [61000.0, 61200.0]  # D3 only, oldest first.
    assert records[0].uri == "ibe/data/spherex/qr3/level2/w1/3/a_D3.fits"
    assert records[0].release == "qr3"
    assert records[0].time_exposure_s == 113.6 and records[0].nasa_poly_icrs.startswith("POLYGON")


def test_tap_success_does_not_call_sia(monkeypatch, no_sleep):
    tap_result = Table(
        {
            "uri": ["ibe/data/spherex/dr1/level2/w/3/x_D3.fits"],
            "time_bounds_lower": [60900.0],
            "time_bounds_upper": [60900.1],
        }
    )
    monkeypatch.setattr(irsa, "_tap_table", lambda query: tap_result)
    monkeypatch.setattr(irsa, "_sia_table", lambda ra, dec: pytest.fail("SIA must not be called"))
    records = irsa.query_frames(269.4, 4.7, 3)
    assert [r.release for r in records] == ["dr1"] and no_sleep == []


def test_error_is_raised_when_tap_and_sia_both_fail(monkeypatch, no_sleep):
    def broken(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(irsa, "_tap_table", broken)
    monkeypatch.setattr(irsa, "_sia_table", broken)
    with pytest.raises(RuntimeError, match="down"):
        irsa.query_frames(269.4, 4.7, 3)


VOTABLE_OK = b"""<?xml version="1.0"?>
<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
 <RESOURCE type="results"><INFO name="QUERY_STATUS" value="OK"/>
  <TABLE><FIELD name="uri" datatype="char" arraysize="*"/>
   <FIELD name="time_bounds_lower" datatype="double"/>
   <DATA><TABLEDATA><TR><TD>ibe/data/spherex/qr3/level2/a.fits</TD><TD>61000.5</TD></TR></TABLEDATA></DATA>
  </TABLE></RESOURCE></VOTABLE>"""

VOTABLE_ERROR = b"""<?xml version="1.0"?>
<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
 <RESOURCE type="results"><INFO name="QUERY_STATUS" value="ERROR">table not found</INFO></RESOURCE>
</VOTABLE>"""


def _fake_request(monkeypatch, content: bytes, status: int = 200):
    calls = []

    def fake(method, url, params=None, data=None, timeout=None):
        calls.append({"method": method, "url": url, "params": params, "data": data, "timeout": timeout})
        return FakeResponse(status, content=content)

    monkeypatch.setattr(irsa.requests, "request", fake)
    return calls


def test_tap_is_queried_directly_with_a_time_limit(monkeypatch):
    calls = _fake_request(monkeypatch, VOTABLE_OK)
    table = irsa._tap_table("SELECT 1")
    assert list(table["uri"]) == ["ibe/data/spherex/qr3/level2/a.fits"]
    assert calls[0]["method"] == "POST" and calls[0]["url"].endswith("/TAP/sync")
    assert calls[0]["data"]["QUERY"] == "SELECT 1"
    assert calls[0]["timeout"] == irsa.QUERY_TIMEOUT_S


def test_sia_asks_every_spherex_collection(monkeypatch):
    calls = _fake_request(monkeypatch, VOTABLE_OK)
    irsa._sia_table(269.4, 4.7)
    params = calls[0]["params"]
    assert calls[0]["method"] == "GET" and calls[0]["url"].endswith("/SIA")
    assert [v for k, v in params if k == "COLLECTION"] == list(irsa.SIA_COLLECTIONS)
    assert ("POS", "CIRCLE 269.4000000 4.7000000 0.0001") in params


VOTABLE_SIA = b"""<?xml version="1.0"?>
<VOTABLE version="1.3" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
 <RESOURCE type="meta"><DESCRIPTION>Self description</DESCRIPTION>
  <RESOURCE type="meta"><TABLE><FIELD name="param" datatype="char" arraysize="*"/>
   <DATA><TABLEDATA><TR><TD>BAND</TD></TR></TABLEDATA></DATA></TABLE></RESOURCE>
 </RESOURCE>
 <RESOURCE type="results"><INFO name="QUERY_STATUS" value="OK"/>
  <TABLE><FIELD ID="col7" name="energy_bandpassname" datatype="char" arraysize="*"/>
   <DATA><TABLEDATA><TR><TD>SPHEREx-D3</TD></TR></TABLEDATA></DATA></TABLE>
 </RESOURCE></VOTABLE>"""


def test_results_table_is_used_even_after_a_meta_resource(monkeypatch):
    # IRSA gives fields an ID different from their name; columns must keep the name.
    _fake_request(monkeypatch, VOTABLE_SIA)
    table = irsa._sia_table(269.4, 4.7)
    assert list(table["energy_bandpassname"]) == ["SPHEREx-D3"]


def test_error_inside_the_votable_is_raised(monkeypatch):
    _fake_request(monkeypatch, VOTABLE_ERROR)
    with pytest.raises(irsa.IrsaQueryError, match="table not found"):
        irsa._tap_table("SELECT 1")


def test_http_error_is_raised(monkeypatch):
    _fake_request(monkeypatch, b"<html>502 Proxy Error</html>", status=502)
    with pytest.raises(requests.HTTPError):
        irsa._sia_table(269.4, 4.7)
