"""Turn SPHEREx cutouts into aligned, displayable images."""

from __future__ import annotations

import io
import logging
import warnings
from dataclasses import dataclass

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from PIL import Image

from . import config

# SPHEREx headers carry SIP coefficients without the "-SIP" CTYPE suffix. Astropy applies them
# anyway (which is what we want) but logs a long notice for every file.
logging.getLogger("astropy").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", category=FITSFixedWarning)

# Pixels with any of these flags are unreliable for photometry and spectra (SPHEREx Explanatory
# Supplement, Table 16). SOURCE is deliberately not included: it only marks known sources.
SCIENCE_EXCLUDED_FLAG_NAMES = (
    "SUR_ERROR",
    "NONFUNC",
    "DICHROIC",
    "MISSING_DATA",
    "HOT",
    "COLD",
    "PHANMISS",
    "NONLINEAR",
    "PERSIST",
    "BLOOM",
    "SNOWBALL",
    "HALO",
)
# For display only pixels without a usable value are hidden. Bright stars saturate SPHEREx
# (OVERFLOW, SUR_ERROR, BLOOM) but still carry finite values; hiding them would punch holes
# exactly where the interesting objects are.
DISPLAY_EXCLUDED_FLAG_NAMES = ("NONFUNC", "MISSING_DATA")
DEFAULT_FLAG_BITS = {
    "SUR_ERROR": 2,
    "NONFUNC": 6,
    "DICHROIC": 7,
    "MISSING_DATA": 9,
    "HOT": 10,
    "COLD": 11,
    "PHANMISS": 14,
    "NONLINEAR": 15,
    "PERSIST": 17,
    "BLOOM": 26,
    "SNOWBALL": 27,
    "HALO": 28,
}


@dataclass
class Cutout:
    image: np.ndarray  # IMAGE - ZODI in MJy/sr, NaN where there is no usable value.
    variance: np.ndarray  # (MJy/sr)^2; invalid values replaced by the cutout median.
    science_bad: np.ndarray  # True where flags make the pixel unreliable for photometry.
    wcs: WCS
    wavelength_um: float
    bandwidth_um: float


def flag_mask(flags_header: fits.Header, names: tuple[str, ...]) -> int:
    """Bitmask for the named flags, read from the MSKNnnnn header keywords when present."""
    bits = dict(DEFAULT_FLAG_BITS)
    for key, value in flags_header.items():
        if key.startswith("MSKN") and value in DEFAULT_FLAG_BITS:
            bits[value] = int(key[4:])
    mask = 0
    for name in names:
        mask |= 1 << bits[name]
    return mask


def read_cutout(data: bytes, ra: float, dec: float) -> Cutout:
    with fits.open(io.BytesIO(data)) as hdul:
        header = hdul["IMAGE"].header
        flags_header = hdul["FLAGS"].header
        image = hdul["IMAGE"].data.astype(np.float64) - hdul["ZODI"].data.astype(np.float64)
        variance = hdul["VARIANCE"].data.astype(np.float64)
        flags = hdul["FLAGS"].data.astype(np.int64)

        hidden = (flags & flag_mask(flags_header, DISPLAY_EXCLUDED_FLAG_NAMES)) != 0
        hidden |= ~np.isfinite(image)
        image[hidden] = np.nan

        valid_variance = np.isfinite(variance) & (variance > 0)
        fallback = float(np.median(variance[valid_variance])) if valid_variance.any() else 1.0
        variance = np.where(valid_variance, variance, fallback)
        variance[hidden] = np.nan

        science_bad = hidden | ((flags & flag_mask(flags_header, SCIENCE_EXCLUDED_FLAG_NAMES)) != 0)

        spatial_wcs = WCS(header)
        wavelength_um = bandwidth_um = float("nan")
        try:
            x, y = spatial_wcs.world_to_pixel_values(ra, dec)
            spectral_wcs = WCS(header, fobj=hdul, key="W")
            spectral_wcs.sip = None
            wavelength, bandwidth = spectral_wcs.pixel_to_world_values(x, y)
            wavelength_um, bandwidth_um = float(wavelength), float(bandwidth)
        except Exception:  # The spectral lookup table is optional for display purposes.
            logging.getLogger(__name__).debug("No spectral WCS for cutout", exc_info=True)

    return Cutout(image, variance, science_bad, spatial_wcs, wavelength_um, bandwidth_um)


def grid_pixels(size_deg: float) -> int:
    """Side of the square output grid, in pixels. Always odd, so the target is the centre."""
    n = int(np.ceil(size_deg / (config.PIXEL_SCALE_ARCSEC / 3600.0)))
    return n + 1 - n % 2


def make_target_grid(ra: float, dec: float, size_deg: float) -> tuple[WCS, tuple[int, int]]:
    """North-up, east-left tangent-plane grid centred on (ra, dec) at the native pixel scale."""
    scale_deg = config.PIXEL_SCALE_ARCSEC / 3600.0
    n = grid_pixels(size_deg)
    wcs = WCS(naxis=2)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    wcs.wcs.crval = [ra, dec]
    wcs.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    wcs.wcs.cdelt = [-scale_deg, scale_deg]
    return wcs, (n, n)


def reproject_nearest(
    values: np.ndarray, source_wcs: WCS, target_wcs: WCS, target_shape: tuple[int, int]
) -> np.ndarray:
    """Resample ``values`` onto the target grid with nearest-neighbour sampling."""
    ny, nx = target_shape
    xs, ys = np.meshgrid(np.arange(nx), np.arange(ny))
    world_ra, world_dec = target_wcs.pixel_to_world_values(xs, ys)
    src_x, src_y = source_wcs.world_to_pixel_values(world_ra, world_dec)
    ix = np.rint(src_x).astype(int)
    iy = np.rint(src_y).astype(int)
    inside = (ix >= 0) & (iy >= 0) & (ix < values.shape[1]) & (iy < values.shape[0])
    out = np.full(target_shape, np.nan)
    out[inside] = values[iy[inside], ix[inside]]
    return out


def crop_center(image: np.ndarray, side: int) -> np.ndarray:
    """Central ``side`` x ``side`` block of an odd-sized square image (``side`` must be odd)."""
    if side % 2 == 0 or side > image.shape[0] or image.shape[0] % 2 == 0:
        raise ValueError(f"Cannot crop {image.shape} to {side} pixels")
    start = (image.shape[0] - side) // 2
    return image[start : start + side, start : start + side]


def coadd(images: list[np.ndarray], variances: list[np.ndarray]) -> np.ndarray:
    """Inverse-variance weighted mean that ignores NaN pixels."""
    stack = np.array(images)
    weights = 1.0 / np.array(variances)
    valid = np.isfinite(stack) & np.isfinite(weights)
    weights = np.where(valid, weights, 0.0)
    total = weights.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = (np.where(valid, stack, 0.0) * weights).sum(axis=0) / total
    result[total == 0] = np.nan
    return result


def fill_enclosed_holes(image: np.ndarray, max_size: int = 16) -> np.ndarray:
    """Fill small groups of NaN pixels fully surrounded by data, for display only.

    The cores of very bright stars saturate and come back from IRSA without a value. Each
    hole is filled with the brightest pixel around it, which is what a saturated core looks
    like. Holes touching the image border (areas without coverage) are left untouched.
    """
    out = image.copy()
    missing = ~np.isfinite(out)
    seen = np.zeros_like(missing)
    ny, nx = out.shape
    for start in zip(*np.nonzero(missing)):
        if seen[start]:
            continue
        component, border_values, touches_edge = [], [], False
        stack = [start]
        seen[start] = True
        while stack:
            y, x = stack.pop()
            component.append((y, x))
            touches_edge |= y in (0, ny - 1) or x in (0, nx - 1)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if (dy or dx) and 0 <= yy < ny and 0 <= xx < nx:
                        if missing[yy, xx]:
                            if not seen[yy, xx]:
                                seen[yy, xx] = True
                                stack.append((yy, xx))
                        else:
                            border_values.append(out[yy, xx])
        if not touches_edge and len(component) <= max_size and border_values:
            fill = max(border_values)
            for y, x in component:
                out[y, x] = fill
    return out


def stretch_limits(images: list[np.ndarray]) -> tuple[float, float]:
    """Display limits shared by all images, so a blink compares like with like."""
    values = np.concatenate([image[np.isfinite(image)] for image in images] or [np.array([])])
    if values.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(values, [1.0, 99.7])
    if high <= low:
        high = low + 1e-6
    return float(low), float(high)


def to_png(image: np.ndarray, low: float, high: float, softening: float = 10.0) -> bytes:
    """Asinh-stretched 8-bit greyscale PNG; flagged pixels become transparent."""
    scaled = np.clip((image - low) / (high - low), 0.0, 1.0)
    scaled = np.arcsinh(scaled * softening) / np.arcsinh(softening)
    finite = np.isfinite(image)
    grey = np.where(finite, np.rint(scaled * 255), 0).astype(np.uint8)
    alpha = np.where(finite, 255, 0).astype(np.uint8)
    # FITS row 0 is the bottom of the image; PNG row 0 is the top.
    pixels = np.flipud(np.dstack([grey, alpha]))
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()
