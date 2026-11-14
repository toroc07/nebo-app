"""Static demo export with SYNTHETIC images (no IRSA, no database), for frontend work.

    python -m tests.demo_export --out ../shared/demo

Each catalogue target gets 3 epochs. The target star moves with its real proper motion (so
Barnard and WISE 0855 visibly shift); the other stars are fixed. Brightness and noise are made
up: use it for layout and interaction, not to judge contrast.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from astropy.io import fits
import numpy as np

from app import config, ephemeris
from app.export import export
from app.irsa import FrameRecord
from app.service import TimelineService
from app.targets import TARGETS
from tests.fakes import make_cutout_bytes
from tests.memory_store import MemoryStore

EPOCH_MJDS = [60888.0, 61072.0, 61254.0]  # About 2025-08, 2026-02 and 2026-08.
ARCSEC_PX = config.PIXEL_SCALE_ARCSEC


def _decorate(data: bytes, static_seed: int, noise_seed: int) -> bytes:
    """Add noise (new every epoch) and fixed background stars (same every epoch)."""
    with fits.open(io.BytesIO(data)) as hdul:
        image = hdul["IMAGE"].data.astype(np.float32)
        ny, nx = image.shape
        yy, xx = np.mgrid[:ny, :nx]
        fixed = np.random.default_rng(static_seed)
        for _ in range(25):
            x, y = fixed.uniform(5, nx - 5), fixed.uniform(5, ny - 5)
            blob = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.3**2))
            image += (fixed.uniform(5, 60) * blob).astype(np.float32)
        image += np.random.default_rng(noise_seed).normal(0, 0.15, image.shape).astype(np.float32)
        hdul["IMAGE"].data = image
        buffer = io.BytesIO()
        hdul.writeto(buffer)
    return buffer.getvalue()


def build(out: Path, detectors: list[int]) -> int:
    store = MemoryStore()
    store.upsert_targets(TARGETS)
    for target in TARGETS:
        records = [
            FrameRecord(
                uri=f"ibe/data/spherex/qr2/level2/demo/{i}/level2_demo_{i}_D1.fits",
                mjd_start=mjd,
                mjd_end=mjd + 0.001,
            )
            for i, mjd in enumerate(EPOCH_MJDS)
        ]

        def fetch(uri: str, ra: float, dec: float, size: float, target=target) -> bytes:
            i = int(uri.split("/")[6])
            years = (EPOCH_MJDS[i] - ephemeris.REFERENCE_MJD) / 365.25
            east = round(target["pm_ra_mas_yr"] / 1000 * years / ARCSEC_PX)
            north = round(target["pm_dec_mas_yr"] / 1000 * years / ARCSEC_PX)
            cutout = make_cutout_bytes(ra, dec, star_offset_px=(east, north), shape=(211, 211))
            return _decorate(cutout, hash_seed(target["slug"]), hash_seed(target["slug"]) + i + 1)

        service = TimelineService(store, query_frames=lambda *_: records, fetch_cutout=fetch)
        patch = service.resolve_patch(target_slug=target["slug"])
        for detector in detectors:
            service.build_now(patch, detector)
    return export(
        store, out, [t["slug"] for t in TARGETS], detectors, list(config.SIZES_DEG)
    )


def hash_seed(text: str) -> int:
    return sum(ord(c) * 31**i for i, c in enumerate(text)) % 2**31


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--detectors", default="3,6")
    args = parser.parse_args()
    raise SystemExit(build(args.out, [int(d) for d in args.detectors.split(",")]))
