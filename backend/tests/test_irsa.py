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
