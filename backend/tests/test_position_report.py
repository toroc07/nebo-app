import io
import math

import numpy as np
import pytest

from app import position_report
from app.position_report import measure_centroid, measure_epoch

SIDE = 41


def star_field(x: float, y: float, *, amp: float = 200.0, sigma: float = 0.9, seed: int = 1):
    """Noisy sky (sigma 1) with one Gaussian star at (x, y), in array (FITS) pixel order."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:SIDE, 0:SIDE]
    star = amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    image = 5.0 + star + rng.normal(0.0, 1.0, (SIDE, SIDE))
    return image.astype(np.float32), np.ones((SIDE, SIDE), dtype=np.float32)


@pytest.mark.parametrize("x, y", [(20.0, 20.0), (20.3, 19.6), (19.55, 20.45), (21.2, 20.8)])
def test_fractional_positions_are_recovered(x, y):
    image, variance = star_field(x, y)
    found = measure_centroid(image, variance, 20.0, 20.0)
    assert found is not None
    assert found.method == "gaussian"
    assert math.hypot(found.x - x, found.y - y) < 0.05
    assert found.snr > 100
    assert found.nan_pixels == 0


def test_nan_saturated_core_is_fitted_from_the_wings():
    x, y = 20.35, 19.7
    image, variance = star_field(x, y, amp=5000.0, sigma=1.3)
    image[19:21, 20:22] = np.nan  # the brightest 2x2 pixels come back without a value
    found = measure_centroid(image, variance, 20.0, 20.0)
    assert found is not None
    assert found.nan_pixels == 4
    assert math.hypot(found.x - x, found.y - y) < 0.1


def test_flat_clipped_core_stays_close():
    x, y = 19.6, 20.3
    image, variance = star_field(x, y, amp=5000.0, sigma=1.2)
    image = np.minimum(image, 1500.0)  # saturated but not NaN: a flat top
    found = measure_centroid(image, variance, 20.0, 20.0)
    assert found is not None
    assert math.hypot(found.x - x, found.y - y) < 0.3


def test_no_detection_returns_none():
    image, variance = star_field(20.0, 20.0, amp=0.0)
    assert measure_centroid(image, variance, 20.0, 20.0) is None


def test_all_nan_window_and_edges_return_none():
    image, variance = star_field(20.0, 20.0)
    image[15:26, 15:26] = np.nan
    assert measure_centroid(image, variance, 20.0, 20.0) is None
    assert measure_centroid(*star_field(1.0, 1.0), 1.0, 1.0) is None


def test_measure_epoch_flips_rows_to_png_and_passes():
    # Star at FITS (x=21.3, y=12.4) -> PNG row SIDE-1-12.4 = 27.6 (north up, row 0 at the top).
    image, variance = star_field(21.3, 12.4)
    epoch = {
        "index": 0,
        "mid_mjd": 60801.5,
        "releases": ["dr1"],
        "expected_position": {"x": 21.0, "y": 28.0, "in_image": True},
    }
    row = measure_epoch(epoch, {"image": image, "variance": variance}, saturated_target=False)
    assert row["date"] == "2025-05-06"  # MJD 60801.5
    mx, my = row["measured"]
    assert abs(mx - 21.3) < 0.05 and abs(my - 27.6) < 0.05
    assert row["offset_px"] == pytest.approx(0.5, abs=0.05)
    assert row["passed"] and not row["saturated"]


def test_collect_and_render_with_a_fake_api():
    image, variance = star_field(20.0, 20.0)
    buffer = io.BytesIO()
    np.savez(buffer, image=image, variance=variance)
    npz = buffer.getvalue()

    class Response:
        def __init__(self, payload=None, content=b"", status_code=200):
            self._payload, self.content, self.status_code = payload, content, status_code

        def json(self):
            return self._payload

    def get(url):
        if url.endswith("/targets"):
            return Response([{"slug": "eps-indi-b", "name": "Epsilon Indi B"}])
        if "/timeline?" in url:
            epochs = [
                {"index": i, "mid_mjd": 60800.0 + 150 * i, "releases": ["dr1"],
                 "expected_position": {"x": 20.0 + 0.3 * i, "y": 20.0, "in_image": True},
                 "npz_url": f"/api/v1/images/{i}.npz"}
                for i in range(2)
            ]
            return Response({"epochs": epochs})
        assert url == f"http://api.test/api/v1/images/{url[-5]}.npz"
        return Response(content=npz)

    rows = position_report.collect("http://api.test/api/v1", get=get)
    assert [r["detector"] for r in rows] == [3, 3]
    assert all(r["passed"] for r in rows)
    text = position_report.render_markdown(rows, "http://api.test/api/v1", rows)
    assert "within 1 px: **2/2**" in text
    assert "| Epsilon Indi B | D3 | 2 |" in text
    assert "## All detectors" in text
