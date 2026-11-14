"""Turn SPHEREx cutouts into aligned, displayable images."""

from __future__ import annotations

import io
import logging
import math
import warnings
from dataclasses import dataclass, field
from typing import Any

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
    zodi_median: float = float("nan")
    target_pix_x: float = float("nan")
    target_pix_y: float = float("nan")
    flags_center: int = 0
    science_bad_fraction: float = float("nan")
    clean_pixel_fraction: float = float("nan")
    corners_icrs: list[list[float]] = field(default_factory=list)
    wcs_header_dict: dict[str, Any] = field(default_factory=dict)


_WCS_HEADER_KEYS = (
    "NAXIS1", "NAXIS2", "CTYPE1", "CTYPE2", "CUNIT1", "CUNIT2", "BUNIT",
    "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2", "CDELT1", "CDELT2",
    "CD1_1", "CD1_2", "CD2_1", "CD2_2", "PC1_1", "PC1_2", "PC2_1", "PC2_2",
    "A_ORDER", "B_ORDER", "AP_ORDER", "BP_ORDER",
)


def _extract_wcs_header_dict(header: fits.Header) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _WCS_HEADER_KEYS:
        if key in header:
            val = header[key]
            if isinstance(val, (str, int, float, bool)):
                out[key] = val
            else:
                out[key] = str(val)
    return out


def _cutout_corners_icrs(wcs: WCS, shape: tuple[int, int]) -> list[list[float]]:
    ny, nx = shape
    px_x = np.array([0.0, float(nx - 1), float(nx - 1), 0.0], dtype=np.float64)
    px_y = np.array([0.0, 0.0, float(ny - 1), float(ny - 1)], dtype=np.float64)
    try:
        ra_vals, dec_vals = wcs.pixel_to_world_values(px_x, px_y)
    except Exception:
        return []
    corners: list[list[float]] = []
    for r, d in zip(np.asarray(ra_vals, dtype=float), np.asarray(dec_vals, dtype=float)):
        if math.isfinite(r) and math.isfinite(d):
            corners.append([round(float(r % 360.0), 7), round(float(d), 7)])
    return corners


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
        zodi_data = hdul["ZODI"].data.astype(np.float64)
        finite_zodi = zodi_data[np.isfinite(zodi_data)]
        zodi_median = float(np.median(finite_zodi)) if finite_zodi.size else float("nan")

        image = hdul["IMAGE"].data.astype(np.float64) - zodi_data
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
        science_bad_fraction = float(np.mean(science_bad)) if science_bad.size else float("nan")
        clean_pixel_fraction = (
            float(1.0 - science_bad_fraction) if math.isfinite(science_bad_fraction) else float("nan")
        )

        spatial_wcs = WCS(header)
        wcs_header_dict = _extract_wcs_header_dict(header)
        corners_icrs = _cutout_corners_icrs(spatial_wcs, image.shape)

        target_pix_x = target_pix_y = float("nan")
        flags_center = 0
        try:
            x, y = spatial_wcs.world_to_pixel_values(ra, dec)
            target_pix_x, target_pix_y = float(x), float(y)
            ix, iy = int(np.rint(target_pix_x)), int(np.rint(target_pix_y))
            if 0 <= iy < flags.shape[0] and 0 <= ix < flags.shape[1]:
                flags_center = int(flags[iy, ix])
        except Exception:
            logging.getLogger(__name__).debug("Failed target pixel projection", exc_info=True)

        wavelength_um = bandwidth_um = float("nan")
        try:
            spectral_wcs = WCS(header, fobj=hdul, key="W")
            spectral_wcs.sip = None
            wavelength, bandwidth = spectral_wcs.pixel_to_world_values(target_pix_x, target_pix_y)
            wavelength_um, bandwidth_um = float(wavelength), float(bandwidth)
        except Exception:  # The spectral lookup table is optional for display purposes.
            logging.getLogger(__name__).debug("No spectral WCS for cutout", exc_info=True)

    return Cutout(
        image=image,
        variance=variance,
        science_bad=science_bad,
        wcs=spatial_wcs,
        wavelength_um=wavelength_um,
        bandwidth_um=bandwidth_um,
        zodi_median=zodi_median,
        target_pix_x=target_pix_x,
        target_pix_y=target_pix_y,
        flags_center=flags_center,
        science_bad_fraction=science_bad_fraction,
        clean_pixel_fraction=clean_pixel_fraction,
        corners_icrs=corners_icrs,
        wcs_header_dict=wcs_header_dict,
    )


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


def compute_sector_coordinates(ra: float, dec: float, size_name: str, side_deg: float) -> dict[str, Any]:
    """Compute exact tangent-plane sky-sector corners and bounding box for a patch size."""
    wcs, (ny, nx) = make_target_grid(ra, dec, side_deg)
    # In north-up east-left TAN projection (cdelt1 < 0), x=-0.5 is East, x=nx-0.5 is West.
    pixel_corners = np.array(
        [
            [nx - 0.5, ny - 0.5],  # NW
            [-0.5, ny - 0.5],      # NE
            [-0.5, -0.5],          # SE
            [nx - 0.5, -0.5],      # SW
        ],
        dtype=np.float64,
    )
    ra_vals, dec_vals = wcs.pixel_to_world_values(pixel_corners[:, 0], pixel_corners[:, 1])
    ras = [round(float(r % 360.0), 7) for r in ra_vals]
    decs = [round(float(d), 7) for d in dec_vals]
    corners = {"NW": [ras[0], decs[0]], "NE": [ras[1], decs[1]], "SE": [ras[2], decs[2]], "SW": [ras[3], decs[3]]}
    polygon_text = (
        f"POLYGON ICRS {ras[1]:.7f} {decs[1]:.7f} {ras[0]:.7f} {decs[0]:.7f} "
        f"{ras[3]:.7f} {decs[3]:.7f} {ras[2]:.7f} {decs[2]:.7f}"
    )
    return {
        "size_name": size_name,
        "center_ra_deg": float(ra % 360.0),
        "center_dec_deg": float(dec),
        "side_deg": float(side_deg),
        "pixel_scale_arcsec": float(config.PIXEL_SCALE_ARCSEC),
        "width_px": int(nx),
        "height_px": int(ny),
        "ra_min_deg": min(ras),
        "ra_max_deg": max(ras),
        "dec_min_deg": min(decs),
        "dec_max_deg": max(decs),
        "corner_nw_ra": ras[0],
        "corner_nw_dec": decs[0],
        "corner_ne_ra": ras[1],
        "corner_ne_dec": decs[1],
        "corner_se_ra": ras[2],
        "corner_se_dec": decs[2],
        "corner_sw_ra": ras[3],
        "corner_sw_dec": decs[3],
        "corners_icrs": corners,
        "footprint_polygon_text": polygon_text,
    }


def compute_all_sector_coordinates(ra: float, dec: float) -> list[dict[str, Any]]:
    """Compute coordinates for all display sizes ('small', 'medium', 'large') plus 'fetch'."""
    sectors = [
        compute_sector_coordinates(ra, dec, name, side_deg)
        for name, side_deg in config.SIZES_DEG.items()
    ]
    sectors.append(compute_sector_coordinates(ra, dec, "fetch", config.FETCH_SIZE_DEG))
    return sectors


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


def coadd(images: list[np.ndarray], variances: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Inverse-variance weighted mean and its variance; NaN pixels are ignored."""
    stack = np.array(images)
    weights = 1.0 / np.array(variances)
    valid = np.isfinite(stack) & np.isfinite(weights)
    weights = np.where(valid, weights, 0.0)
    total = weights.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (np.where(valid, stack, 0.0) * weights).sum(axis=0) / total
        variance = 1.0 / total
    mean[total == 0] = np.nan
    variance[total == 0] = np.nan
    return mean, variance


def to_npz(image: np.ndarray, variance: np.ndarray) -> bytes:
    """Float32 data for analysis (epoch subtraction, photometry); no stretch, no hole filling."""
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer, image=image.astype(np.float32), variance=variance.astype(np.float32)
    )
    return buffer.getvalue()


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
