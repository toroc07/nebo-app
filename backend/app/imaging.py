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
# Saturation: the ramp overflowed or could not be fit. The core of a bright star is NaN or clipped.
SATURATION_FLAG_NAMES = ("OVERFLOW", "SUR_ERROR")
DEFAULT_FLAG_BITS = {
    "OVERFLOW": 1,
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
    saturated: np.ndarray | None = None  # True where OVERFLOW or SUR_ERROR is set.


def saturated_near(
    saturated: np.ndarray, x: float | None, y: float | None, radius: int = 2
) -> bool | None:
    """Any saturated pixel in the (2r+1)^2 box around (x, y), the ePSF photometry aperture.

    None when the position is not finite or falls outside the cutout.
    """
    if x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
        return None
    ix, iy = round(x), round(y)
    ny, nx = saturated.shape
    if not (0 <= ix < nx and 0 <= iy < ny):
        return None
    return bool(saturated[max(0, iy - radius) : iy + radius + 1, max(0, ix - radius) : ix + radius + 1].any())


def pixel_to_ujy() -> float:
    """MJy/sr in one native pixel -> µJy."""
    return math.radians(config.PIXEL_SCALE_ARCSEC / 3600.0) ** 2 * 1e12


def local_background(
    image: np.ndarray,
    bad: np.ndarray,
    x: float,
    y: float,
    radii: tuple[float, float] | None = None,
    min_pixels: int | None = None,
) -> tuple[float, float, int, float] | None:
    """Sky level around (x, y): clipped median of the valid annulus pixels, in the image's units.

    Returns (level per pixel, error of that level, pixels used, pixel noise σ), or None when the
    position is not finite or too few pixels remain. Neighbouring stars in the annulus are removed
    by iterative 3-sigma clipping (MAD-based); the level's error is 1.2533·σ/√n, that of a median.
    """
    r_in, r_out = radii or config.LOCAL_BACKGROUND_ANNULUS_PX
    need = config.LOCAL_BACKGROUND_MIN_PIXELS if min_pixels is None else min_pixels
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    ny, nx = image.shape
    reach = int(math.ceil(r_out)) + 1
    x0, x1 = max(0, int(x) - reach), min(nx, int(x) + reach + 1)
    y0, y1 = max(0, int(y) - reach), min(ny, int(y) + reach + 1)
    if x0 >= x1 or y0 >= y1:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r = np.hypot(xx - x, yy - y)
    box = image[y0:y1, x0:x1]
    values = box[(r >= r_in) & (r <= r_out) & ~bad[y0:y1, x0:x1] & np.isfinite(box)]
    for _ in range(5):
        if values.size < need:
            return None
        median = np.median(values)
        sigma = 1.4826 * np.median(np.abs(values - median))
        if sigma <= 0:
            break
        keep = np.abs(values - median) <= 3.0 * sigma
        if keep.all():
            break
        values = values[keep]
    if values.size < need:
        return None
    median = float(np.median(values))
    sigma = float(1.4826 * np.median(np.abs(values - median)))
    return median, 1.2533 * sigma / math.sqrt(values.size), int(values.size), sigma


# A peak this many pixel-noise σ above the sky counts as a real source when locating the light.
PEAK_MIN_SNR = 5.0


def peak_offset(
    image: np.ndarray, x: float, y: float, level: float, pixel_sigma: float, reach: int = 2
) -> float | None:
    """Distance in pixels from (x, y) to the brightest pixel in the (2·reach+1)² box around it.

    None when that pixel is not a significant source (< PEAK_MIN_SNR·σ above the sky ``level``):
    then there is no light to locate. A source on the object gives at most ~0.7 px (half a pixel
    diagonal); ≥ 1.2 px means the light in the aperture peaks on a neighbour, not on the object.
    """
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(level)) or pixel_sigma <= 0:
        return None
    ix, iy = int(np.rint(x)), int(np.rint(y))
    ny, nx = image.shape
    x0, x1 = max(0, ix - reach), min(nx, ix + reach + 1)
    y0, y1 = max(0, iy - reach), min(ny, iy + reach + 1)
    box = image[y0:y1, x0:x1]
    if box.size == 0 or not np.isfinite(box).any():
        return None
    py, px = np.unravel_index(int(np.nanargmax(box)), box.shape)
    if box[py, px] - level < PEAK_MIN_SNR * pixel_sigma:
        return None
    return float(math.hypot(x0 + px - x, y0 + py - y))


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
        saturated = (flags & flag_mask(flags_header, SATURATION_FLAG_NAMES)) != 0
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
        saturated=saturated,
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


def target_world(target_wcs: WCS, target_shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Sky coordinates of every target pixel; the same for all frames of a build."""
    ny, nx = target_shape
    xs, ys = np.meshgrid(np.arange(nx), np.arange(ny))
    return target_wcs.pixel_to_world_values(xs, ys)


def reproject_nearest_many(
    arrays: list[np.ndarray],
    source_wcs: WCS,
    target_wcs: WCS,
    target_shape: tuple[int, int],
    world: tuple[np.ndarray, np.ndarray] | None = None,
) -> list[np.ndarray]:
    """Resample arrays sharing one source WCS onto the target grid (nearest neighbour).

    The pixel lookup is computed once for all arrays; pass ``world`` to reuse the target
    grid's sky coordinates across frames.
    """
    world_ra, world_dec = world or target_world(target_wcs, target_shape)
    src_x, src_y = source_wcs.world_to_pixel_values(world_ra, world_dec)
    ix = np.rint(src_x).astype(int)
    iy = np.rint(src_y).astype(int)
    outs = []
    for values in arrays:
        inside = (ix >= 0) & (iy >= 0) & (ix < values.shape[1]) & (iy < values.shape[0])
        out = np.full(target_shape, np.nan)
        out[inside] = values[iy[inside], ix[inside]]
        outs.append(out)
    return outs


def reproject_nearest(
    values: np.ndarray, source_wcs: WCS, target_wcs: WCS, target_shape: tuple[int, int]
) -> np.ndarray:
    """Resample ``values`` onto the target grid with nearest-neighbour sampling."""
    return reproject_nearest_many([values], source_wcs, target_wcs, target_shape)[0]


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


def to_diff_png(first: np.ndarray, second: np.ndarray, softening: float = 10.0) -> tuple[bytes, float]:
    """RGBA PNG of ``second - first``: red = brighter in ``second``, blue = fainter.

    The scale is symmetric (0 is black) and ends at the 99.7th percentile of |difference|, which
    is returned too (MJy/sr). Pixels without data in either image are transparent.
    """
    diff = second - first
    finite = np.isfinite(diff)
    limit = float(np.percentile(np.abs(diff[finite]), 99.7)) if finite.any() else 0.0
    limit = max(limit, 1e-6)
    scaled = np.arcsinh(np.clip(np.abs(diff) / limit, 0.0, 1.0) * softening) / np.arcsinh(softening)
    level = np.where(finite, np.rint(scaled * 255), 0).astype(np.uint8)
    red = np.where(diff > 0, level, 0).astype(np.uint8)
    blue = np.where(diff < 0, level, 0).astype(np.uint8)
    alpha = np.where(finite, 255, 0).astype(np.uint8)
    pixels = np.flipud(np.dstack([red, np.zeros_like(red), blue, alpha]))
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue(), limit


def _stretch_channel(channel: np.ndarray, softening: float = 10.0) -> np.ndarray:
    """Asinh stretch of a single float32 band to [0, 255] uint8."""
    finite = np.isfinite(channel)
    if not finite.any():
        return np.zeros(channel.shape, dtype=np.uint8)
    lo, hi = np.percentile(channel[finite], [1.0, 99.5])
    span = max(float(hi - lo), 1e-6)
    norm = np.clip((channel - lo) / span, 0.0, 1.0)
    scaled = np.arcsinh(norm * softening) / np.arcsinh(softening)
    return np.where(finite, np.rint(scaled * 255), 0).astype(np.uint8)


def to_rgb_png(
    red: np.ndarray, green: np.ndarray, blue: np.ndarray, softening: float = 10.0
) -> bytes:
    """RGBA false-color PNG combining three SPHEREx detector bands (north up, east left).

    Each channel is stretched independently with ``asinh`` between its 1st and 99.5th
    percentiles. Pixels missing data in any of the three bands are transparent.
    """
    finite = np.isfinite(red) & np.isfinite(green) & np.isfinite(blue)
    r_u8 = _stretch_channel(red, softening)
    g_u8 = _stretch_channel(green, softening)
    b_u8 = _stretch_channel(blue, softening)
    alpha = np.where(finite, 255, 0).astype(np.uint8)
    pixels = np.flipud(np.dstack([r_u8, g_u8, b_u8, alpha]))
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()


# Mask layer colour: the viewer's amber for data warnings (#fbbf24).
MASK_RGB = (251, 191, 36)


def to_mask_png(image: np.ndarray) -> tuple[bytes, float]:
    """RGBA PNG on the image's grid: amber where the float data is NaN, transparent elsewhere.

    Uses the float co-add, not the display PNG: the PNG fills small enclosed holes (saturated
    star cores, ``fill_enclosed_holes``), which have no valid data. Flipped like ``to_png``
    (north up). Also returns the masked share of the pixels.
    """
    missing = ~np.isfinite(image)
    pixels = np.zeros(missing.shape + (4,), dtype=np.uint8)
    pixels[missing] = (*MASK_RGB, 255)
    buffer = io.BytesIO()
    Image.fromarray(np.flipud(pixels)).save(buffer, format="PNG")
    return buffer.getvalue(), float(missing.mean()) if missing.size else 0.0


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


# Display palettes: (position 0-1, (r, g, b)) stops. Colour is added for display only; the data
# is a single band, so it carries no real colour.
PALETTES = {
    "amber": [(0.0, (0, 0, 0)), (0.6, (255, 176, 0)), (1.0, (255, 255, 255))],
    # Matplotlib "inferno" sampled every 0.1 (the palette IRSA's SPHEREx tutorial uses).
    "inferno": [
        (0.0, (0, 0, 4)), (0.1, (22, 11, 57)), (0.2, (66, 10, 104)), (0.3, (106, 23, 110)),
        (0.4, (147, 38, 103)), (0.5, (188, 55, 84)), (0.6, (221, 81, 58)), (0.7, (243, 120, 25)),
        (0.8, (252, 165, 10)), (0.9, (246, 215, 70)), (1.0, (252, 255, 164)),
    ],
}


def colorize_png(png: bytes, palette: str) -> bytes:
    """Recolour a grey+alpha PNG from ``to_png`` with a palette; alpha is kept."""
    grey_alpha = np.asarray(Image.open(io.BytesIO(png)).convert("LA"))
    stops = PALETTES[palette]
    level = grey_alpha[..., 0] / 255.0
    rgb = [
        np.rint(np.interp(level, [x for x, _ in stops], [color[i] for _, color in stops]))
        for i in range(3)
    ]
    pixels = np.dstack([*rgb, grey_alpha[..., 1]]).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()
