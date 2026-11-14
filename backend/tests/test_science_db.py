"""Tests for sector coordinates, NASA exposure persistence, .npz API, catalogs, ML cache, and GCS."""

from __future__ import annotations

import io
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, gcs_storage, irsa, science_catalogs
from app.main import app, get_service, get_store
from app.service import TimelineService
from app.targets import TARGETS
from tests.fakes import make_cutout_bytes
from tests.memory_store import MemoryStore
from tests.test_service import wait_until_settled

RA, DEC = 269.446223, 4.76878


def _make_rich_records(mjds: list[float]) -> list[irsa.FrameRecord]:
    return [
        irsa.FrameRecord(
            uri=f"ibe/data/spherex/qr3/level2/x/{i}/level2_x_{i}_D3.fits",
            mjd_start=mjd,
            mjd_end=mjd + 0.01,
            plane_id=f"plane-{i}",
            nasa_poly_icrs=f"POLYGON ICRS {RA-0.1:.4f} {DEC-0.1:.4f} {RA+0.1:.4f} {DEC-0.1:.4f} {RA+0.1:.4f} {DEC+0.1:.4f} {RA-0.1:.4f} {DEC+0.1:.4f}",
            energy_bounds_lower_m=1.63e-6,
            energy_bounds_upper_m=2.41e-6,
            time_exposure_s=112.5,
        )
        for i, mjd in enumerate(mjds)
    ]


@pytest.fixture
def client():
    store = MemoryStore()
    store.upsert_targets(TARGETS)
    store.upsert_spherex_channels(science_catalogs.SPHEREX_102_CHANNELS)
    store.upsert_spectral_indices(science_catalogs.SPHEREX_17_INDICES)
    service = TimelineService(
        store,
        query_frames=lambda *args: _make_rich_records([60914.0, 61110.0]),
        fetch_cutout=lambda uri, ra, dec, size: make_cutout_bytes(ra, dec, shape=(211, 211)),
    )
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_service] = lambda: service
    yield TestClient(app), service, store
    app.dependency_overrides.clear()


def test_102_channels_and_17_indices_catalogs():
    assert len(science_catalogs.SPHEREX_102_CHANNELS) == 102
    blank_ids = [ch.channel_id for ch in science_catalogs.SPHEREX_102_CHANNELS if ch.is_blankch]
    assert blank_ids == [51, 52]
    assert len(science_catalogs.SPHEREX_17_INDICES) == 17

    assert science_catalogs.channel_for_wavelength(3, 1.905) == 41
    assert science_catalogs.channel_for_wavelength(6, 4.669) == 93
    assert science_catalogs.channel_for_wavelength(3, float("nan")) is None

    # 3% systematic floor check: sqrt(4^2 + (0.03 * 100)^2) = sqrt(16 + 9) = 5.0
    assert science_catalogs.compute_reported_sigma(100.0, 4.0) == pytest.approx(5.0)

    nsdi, sigma = science_catalogs.compute_nsdi(3.0, 0.1, 1.0, 0.1)
    assert nsdi == pytest.approx(0.5)
    assert sigma is not None and math.isfinite(sigma) and sigma > 0.0
    assert science_catalogs.compute_nsdi(-1.0, 0.1, 1.0, 0.1) == (None, None)


def test_sector_coordinates_persisted_on_patch_and_served_via_api(client):
    http, service, store = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    sectors = store.list_sector_coordinates(patch.id)
    assert [s["size_name"] for s in sectors] == ["small", "medium", "large", "fetch"]
    for sector in sectors:
        assert sector["center_ra_deg"] == pytest.approx(RA)
        assert sector["center_dec_deg"] == pytest.approx(DEC)
        assert sector["ra_min_deg"] < RA < sector["ra_max_deg"]
        assert sector["dec_min_deg"] < DEC < sector["dec_max_deg"]
        assert set(sector["corners_icrs"]) == {"NW", "NE", "SE", "SW"}
        assert sector["footprint_polygon_text"].startswith("POLYGON ICRS ")

    resp = http.get(f"/api/v1/patches/{patch.id}/sectors")
    assert resp.status_code == 200
    body = resp.json()
    assert body["patch_id"] == patch.id and len(body["sectors"]) == 4
    assert http.get("/api/v1/patches/999999/sectors").status_code == 404


def test_timeline_stores_nasa_sector_exposures_and_serves_npz(client):
    http, service, store = client
    patch = service.resolve_patch(ra=RA, dec=DEC)
    http.get("/api/v1/timeline", params={"ra": RA, "dec": DEC, "size": "large", "detector": 3})
    wait_until_settled(service, patch, detector=3, size="large")

    # Verify per-exposure NASA sector metadata is saved
    exposures = store.list_nasa_sector_exposures(patch.id, detector=3)
    assert len(exposures) == 2
    first_exp = exposures[0]
    assert first_exp["plane_id"] == "plane-0"
    assert first_exp["nasa_poly_icrs"].startswith("POLYGON ICRS ")
    assert len(first_exp["cutout_corners_icrs"]) == 4
    assert "CTYPE1" in first_exp["wcs_header_json"]
    assert first_exp["aperture_sigma_reported_ujy"] >= first_exp["aperture_sigma_stat_ujy"]
    assert 0.0 <= first_exp["clean_pixel_fraction"] <= 1.0

    # Verify NPZ endpoint and npz_url on large timeline response
    large_resp = http.get("/api/v1/timeline", params={"ra": RA, "dec": DEC, "size": "large", "detector": 3})
    assert large_resp.status_code == 200
    epochs = large_resp.json()["epochs"]
    assert "npz_url" in epochs[0]
    npz_resp = http.get(epochs[0]["npz_url"])
    assert npz_resp.status_code == 200
    assert npz_resp.headers["content-type"] == "application/octet-stream"
    arrays = np.load(io.BytesIO(npz_resp.content))
    assert arrays["image"].dtype == np.float32
    assert arrays["variance"].dtype == np.float32

    # Small timeline should omit npz_url
    small_resp = http.get("/api/v1/timeline", params={"ra": RA, "dec": DEC, "size": "small", "detector": 3})
    assert "npz_url" not in small_resp.json()["epochs"][0]
    assert http.get("/api/v1/images/999999.npz").status_code == 404


def test_patch_spectrum_enforces_blankch_51_52_null_and_models_cache():
    store = MemoryStore()
    patch = store.create_patch(134.86, -47.24, "wise-0855")

    # Attempt to sneak 0.0 into BLANKCH channels 51 and 52 (0-based 50 and 51)
    flux = [5.0 + i * 0.1 for i in range(102)]
    flux[50] = 0.0
    flux[51] = 0.0
    spec = store.save_patch_spectrum(
        patch.id,
        -1,
        {
            "flux_mjy": flux,
            "variance_mjy2": [0.04] * 102,
            "valid_mask": [True] * 102,
            "channel_hit_counts": [4] * 102,
            "band_coadd_flux_mjy": {"2": 1.0, "6": 12.0},
        },
        indices=[
            {
                "index_code": "COLOR_PLANET_X",
                "value": 0.846,
                "uncertainty": 0.05,
            }
        ],
    )
    assert spec["flux_mjy"][50] is None and spec["flux_mjy"][51] is None
    assert spec["valid_mask"][50] is False and spec["valid_mask"][51] is False
    assert spec["valid_channel_count"] == 100
    assert spec["indices"][0]["is_significant_3s"] is True

    m1 = store.save_model1_attribution(
        patch.id,
        -1,
        {
            "feature_vector": {"psf_chi2_red": 1.2, "clean_pixel_fraction": 0.96},
            "predicted_class": "REAL_TRANSIENT",
            "temperature_t": 1.15,
            "probabilities": {"REAL_TRANSIENT": 0.92, "SOLAR_SYSTEM_MOVER": 0.05, "INSTRUMENT_ARTIFACT": 0.03},
            "treeshap_values": {"psf_chi2_red": 0.41},
            "citizen_level1": {"headline": "Confirmado"},
            "researcher_level2": {"treeshap": {"psf_chi2_red": 0.41}},
        },
    )
    m2 = store.save_model2_classification(
        patch.id,
        {
            "spectrum_id": spec["id"],
            "predicted_class": "T_Y_DWARF",
            "best_template_name": "sonora_t250_logg4.5",
            "template_teff_k": 250.0,
            "template_log_g": 4.5,
            "chi2_reduced": 1.12,
            "dof": 98,
            "valid_channels_used": 100,
            "bayesian_posteriors": {"T_Y_DWARF": 0.97},
            "citizen_level1": {"label": "Enana Y ultra-fría"},
            "researcher_level2": {"blankch_excluded": [51, 52]},
        },
    )
    m3 = store.save_model3_forecast(
        patch.id,
        {
            "model1_attribution_id": m1["id"],
            "gp_hyperparams": {"kernel": "Matern32", "ell_days": 140.0},
            "forecast_series": [{"mjd": 61400.0, "flux_mean": 11.8, "flux_sigma": 0.6}],
            "predicted_cone": {"sigma_arcsec": 4.2},
            "z_alert": 1.1,
            "mahalanobis_d2": 1.21,
            "delta_log_likelihood": 0.3,
            "alert_triggered": False,
            "citizen_level1": {"status": "Estable"},
            "researcher_level2": {"model1_id": m1["id"]},
        },
    )
    vote = store.save_citizen_vote(patch.id, 0, "CONFIRM_OBJECT", voter_token="anon-1")
    assert m2["predicted_class"] == "T_Y_DWARF"
    assert m3["model1_attribution_id"] == m1["id"]
    assert vote["vote"] == "CONFIRM_OBJECT"
    assert len(store.list_citizen_votes(patch.id)) == 1


def test_catalog_endpoints_and_api_cache_reuse(client):
    http, _, store = client
    ch_resp = http.get("/api/v1/catalogs/channels")
    assert ch_resp.status_code == 200
    channels = ch_resp.json()
    assert len(channels) == 102
    assert channels[50]["is_blankch"] is True and channels[51]["is_blankch"] is True

    idx_resp = http.get("/api/v1/catalogs/spectral-indices")
    assert idx_resp.status_code == 200
    assert len(idx_resp.json()) == 17

    store.set_cached_api(
        "k1", "irsa_tap", [{"uri": "ibe/data/spherex/test.fits"}], row_count=1
    )
    assert store.get_cached_api("k1")["row_count"] == 1


def test_gcs_storage_client_fake_bucket(monkeypatch, tmp_path):
    monkeypatch.delenv("NEBO_GCS_BUCKET", raising=False)
    assert gcs_storage.GCSStorageClient.from_env() is None

    storage_blobs: dict[str, bytes] = {}

    class FakeBlob:
        def __init__(self, name: str) -> None:
            self.name = name
            self.crc32c = "fakeCrc=="

        def upload_from_string(self, data: bytes, content_type: str = "") -> None:
            storage_blobs[self.name] = bytes(data)

        def exists(self) -> bool:
            return self.name in storage_blobs

        def download_as_bytes(self) -> bytes:
            return storage_blobs[self.name]

    class FakeBucket:
        def blob(self, name: str) -> FakeBlob:
            return FakeBlob(name)

    class FakeClient:
        def bucket(self, name: str) -> FakeBucket:
            return FakeBucket()

    client = gcs_storage.GCSStorageClient(
        bucket_name="run-sources-traficcolector-us-central1",
        project="traficcolector",
        client=FakeClient(),
    )
    obj_name = client.build_object_name("cutouts", "ab", "test.fits")
    ref = client.upload_bytes(obj_name, b"FITSBYTES", content_type="application/fits")
    assert ref.gcs_uri == "gs://run-sources-traficcolector-us-central1/nebo-spherex/cutouts/ab/test.fits"
    dest = tmp_path / "downloaded.fits"
    assert client.download_file(obj_name, dest) is True
    assert dest.read_bytes() == b"FITSBYTES"
