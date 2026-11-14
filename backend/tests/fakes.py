"""Synthetic SPHEREx-like cutouts so tests never touch IRSA."""

from __future__ import annotations

import io

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from app.irsa import FrameRecord

SCALE_DEG = 6.15 / 3600.0


def make_cutout_bytes(
    ra: float,
    dec: float,
    star_offset_px: tuple[int, int] = (0, 0),
    shape: tuple[int, int] = (31, 31),
    rotated_180: bool = False,
    flag_value_at_star: int = 0,
) -> bytes:
    """A cutout centred on (ra, dec) with one bright pixel offset from the centre.

    ``star_offset_px`` is (east, north) in pixels, so the star's sky position does not depend
    on the cutout orientation.
    """
    ny, nx = shape
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crval = [ra, dec]
    wcs.wcs.crpix = [(nx + 1) / 2, (ny + 1) / 2]
    # Standard orientation is east-left (cdelt1 < 0), north-up (cdelt2 > 0).
    wcs.wcs.cdelt = [SCALE_DEG, -SCALE_DEG] if rotated_180 else [-SCALE_DEG, SCALE_DEG]

    image = np.full(shape, 1.0, dtype=np.float32)
    zodi = np.full(shape, 0.25, dtype=np.float32)
    variance = np.full(shape, 0.01, dtype=np.float32)
    flags = np.zeros(shape, dtype=np.int32)

    east, north = star_offset_px
    sign = -1 if rotated_180 else 1
    cx, cy = (nx - 1) // 2, (ny - 1) // 2
    sx, sy = cx - sign * east, cy + sign * north
    image[sy, sx] = 101.0
    flags[sy, sx] = flag_value_at_star

    header = wcs.to_header()
    hdus = fits.HDUList(
        [
            fits.PrimaryHDU(),
            fits.ImageHDU(image, header=header, name="IMAGE"),
            fits.ImageHDU(flags, name="FLAGS"),
            fits.ImageHDU(variance, name="VARIANCE"),
            fits.ImageHDU(zodi, name="ZODI"),
        ]
    )
    buffer = io.BytesIO()
    hdus.writeto(buffer)
    return buffer.getvalue()


def make_records(mjds: list[float]) -> list[FrameRecord]:
    return [
        FrameRecord(
            uri=f"ibe/data/spherex/qr3/level2/test/{i}/level2_test_{i}_D1.fits",
            mjd_start=mjd,
            mjd_end=mjd + 0.001,
        )
        for i, mjd in enumerate(mjds)
    ]
