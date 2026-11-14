"""Access to SPHEREx Level 2 spectral images at NASA/IPAC IRSA.

Follows the method of the official IRSA tutorial "Download a collection of SPHEREx Spectral
Image cutouts": a TAP query lists every image that covers a position, and appending
``?center=<ra>,<dec>d&size=<deg>`` to an image URL makes IRSA return only a cutout.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
from astroquery.ipac.irsa import Irsa

from . import config
from .gcs_storage import GCSStorageClient

log = logging.getLogger(__name__)

SPHEREX_PATH_PREFIX = "ibe/data/spherex/"

# Approximate wavelength coverage of each detector array, in microns.
DETECTOR_WAVELENGTH_RANGE_UM: dict[int, tuple[float, float]] = {
    1: (0.75, 1.09),
    2: (1.10, 1.62),
    3: (1.63, 2.41),
    4: (2.42, 3.82),
    5: (3.83, 4.41),
    6: (4.42, 5.00),
}


@dataclass(frozen=True)
class FrameRecord:
    """One SPHEREx spectral image (one exposure of one detector) covering the target."""

    uri: str  # Path relative to the IRSA root, starting with "ibe/data/spherex/".
    mjd_start: float
    mjd_end: float
    plane_id: str | None = None
    nasa_poly_icrs: str | None = None
    energy_bounds_lower_m: float | None = None
    energy_bounds_upper_m: float | None = None
    time_exposure_s: float | None = None

    @property
    def release(self) -> str:
        """Data release the image belongs to, e.g. "dr1" or "qr3"."""
        parts = self.uri.split("/")
        return parts[3] if len(parts) > 3 else "unknown"


def bandpass_name(detector: int) -> str:
    if detector not in DETECTOR_WAVELENGTH_RANGE_UM:
        raise ValueError(f"Detector must be between 1 and 6, got {detector}.")
    return f"SPHEREx-D{detector}"


def build_frames_query(ra: float, dec: float, detector: int) -> str:
    # ra, dec and detector are validated numbers, so formatting them into ADQL is safe.
    return f"""
SELECT a.uri, p.time_bounds_lower, p.time_bounds_upper,
       p.planeid, p.poly, p.energy_bounds_lower, p.energy_bounds_upper, p.time_exposure
FROM spherex.artifact a
JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', {ra:.7f}, {dec:.7f}), p.poly)
  AND p.energy_bandpassname = '{bandpass_name(detector)}'
ORDER BY p.time_bounds_lower
"""


def _opt_str(row, cols: set[str], name: str) -> str | None:
    if name not in cols:
        return None
    val = row[name]
    if val is None or np.ma.is_masked(val):
        return None
    text = str(val).strip()
    return text or None


def _opt_float(row, cols: set[str], name: str) -> float | None:
    if name not in cols:
        return None
    val = row[name]
    if val is None or np.ma.is_masked(val):
        return None
    f = float(val)
    return f if np.isfinite(f) else None


def query_frames(ra: float, dec: float, detector: int) -> list[FrameRecord]:
    """List the spectral images of one detector that cover (ra, dec), oldest first."""
    table = Irsa.query_tap(build_frames_query(ra, dec, detector)).to_table()
    cols = set(table.colnames)
    records = []
    for row in table:
        uri = str(row["uri"])
        if not uri.startswith(SPHEREX_PATH_PREFIX):
            log.warning("Skipping unexpected IRSA path: %s", uri)
            continue
        records.append(
            FrameRecord(
                uri=uri,
                mjd_start=float(row["time_bounds_lower"]),
                mjd_end=float(row["time_bounds_upper"]),
                plane_id=_opt_str(row, cols, "planeid"),
                nasa_poly_icrs=_opt_str(row, cols, "poly"),
                energy_bounds_lower_m=_opt_float(row, cols, "energy_bounds_lower"),
                energy_bounds_upper_m=_opt_float(row, cols, "energy_bounds_upper"),
                time_exposure_s=_opt_float(row, cols, "time_exposure"),
            )
        )
    return records


def cutout_url(uri: str, ra: float, dec: float, size_deg: float) -> str:
    return f"{config.IRSA_BASE_URL}/{uri}?center={ra:.7f},{dec:.7f}d&size={size_deg:.5f}"


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    return config.CACHE_DIR / "cutouts" / digest[:2] / f"{digest}.fits"


RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_BACKOFF_S = 60.0


def _backoff_seconds(attempt: int, response: requests.Response | None) -> float:
    """Exponential backoff with jitter; honours Retry-After when IRSA sends it."""
    retry_after = response.headers.get("Retry-After") if response is not None else None
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), MAX_BACKOFF_S)
    return min(5.0 * 2**attempt, MAX_BACKOFF_S) * random.uniform(0.8, 1.2)


def fetch_cutout(uri: str, ra: float, dec: float, size_deg: float, retries: int = 4) -> bytes:
    """Download a cutout as multi-extension FITS bytes, using an on-disk cache.

    IRSA answers 503 when it is overloaded (common during the hackathon), so transient
    errors are retried with exponential backoff. Other HTTP errors fail at once.
    """
    url = cutout_url(uri, ra, dec, size_deg)
    path = _cache_path(url)
    if path.exists():
        return path.read_bytes()

    gcs = GCSStorageClient.from_env()
    gcs_object = gcs.build_object_name("cutouts", path.parent.name, path.name) if gcs else None
    if gcs is not None and gcs_object is not None:
        try:
            if gcs.download_file(gcs_object, path):
                return path.read_bytes()
        except Exception:
            log.warning("GCS cutout lookup failed for %s; falling back to IRSA", url, exc_info=True)

    for attempt in range(retries + 1):
        response = None
        try:
            response = requests.get(url, timeout=config.HTTP_TIMEOUT_S)
            response.raise_for_status()
        except requests.RequestException as error:
            status = response.status_code if response is not None else None
            retryable = status is None or status in RETRYABLE_STATUS
            if not retryable or attempt == retries:
                raise RuntimeError(f"Could not download cutout {uri}: {error}") from error
            wait = _backoff_seconds(attempt, response)
            log.info("IRSA %s, retrying in %.0f s: %s", status or "error", wait, uri)
            time.sleep(wait)
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(response.content)
        tmp.replace(path)
        if gcs is not None and gcs_object is not None:
            try:
                gcs.upload_bytes(gcs_object, response.content, content_type="application/fits")
            except Exception:
                log.warning("GCS cutout upload failed for %s", url, exc_info=True)
        return response.content
    raise AssertionError("unreachable")
