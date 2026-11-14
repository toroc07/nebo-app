import io

import numpy as np
from astropy.io import fits
from PIL import Image

from app import imaging
from tests.fakes import make_cutout_bytes

RA, DEC = 269.446223, 4.768780


def _star_position(image: np.ndarray) -> tuple[int, int]:
    y, x = np.unravel_index(np.nanargmax(image), image.shape)
    return int(x), int(y)


def test_read_cutout_subtracts_zodi():
    cutout = imaging.read_cutout(make_cutout_bytes(RA, DEC), RA, DEC)
    assert np.nanmin(cutout.image) == 0.75  # 1.0 - 0.25
    assert np.nanmax(cutout.image) == 100.75
    assert np.isnan(cutout.wavelength_um)  # Synthetic file has no WCS-WAVE table.


def test_saturated_star_stays_visible_but_is_marked_for_science():
    data = make_cutout_bytes(RA, DEC, flag_value_at_star=1 << 26)  # BLOOM
    cutout = imaging.read_cutout(data, RA, DEC)
    assert np.nanmax(cutout.image) == 100.75
    assert cutout.science_bad.sum() == 1


def test_pixel_without_value_is_hidden():
    data = make_cutout_bytes(RA, DEC, flag_value_at_star=1 << 6)  # NONFUNC
    cutout = imaging.read_cutout(data, RA, DEC)
    assert np.isnan(cutout.image).sum() == 1 and np.nanmax(cutout.image) == 0.75
    assert np.isnan(cutout.variance).sum() == 1


def test_flag_mask_follows_header_bit_names():
    header = fits.Header()
    header["MSKN0003"] = "HOT"  # Moved from its usual bit 10.
    mask = imaging.flag_mask(header, imaging.SCIENCE_EXCLUDED_FLAG_NAMES)
    assert mask & (1 << 3)
    assert not mask & (1 << 10)
    assert not mask & (1 << 21)  # SOURCE is never excluded.


def test_crop_center_keeps_the_central_pixel():
    image = np.arange(49.0).reshape(7, 7)
    cropped = imaging.crop_center(image, 3)
    assert cropped.shape == (3, 3) and cropped[1, 1] == image[3, 3]
    assert imaging.grid_pixels(0.05) % 2 == 1


def test_target_grid_is_odd_and_centred():
    wcs, shape = imaging.make_target_grid(RA, DEC, 0.05)
    assert shape[0] == shape[1] and shape[0] % 2 == 1
    x, y = wcs.world_to_pixel_values(RA, DEC)
    assert (round(float(x)), round(float(y))) == ((shape[1] - 1) // 2, (shape[0] - 1) // 2)


def test_reprojection_puts_north_up_for_any_input_orientation():
    grid_wcs, grid_shape = imaging.make_target_grid(RA, DEC, 0.05)
    centre = (grid_shape[1] - 1) // 2
    positions = []
    for rotated in (False, True):
        cutout = imaging.read_cutout(
            make_cutout_bytes(RA, DEC, star_offset_px=(3, 5), rotated_180=rotated), RA, DEC
        )
        image = imaging.reproject_nearest(cutout.image, cutout.wcs, grid_wcs, grid_shape)
        positions.append(_star_position(image))

    # East is left (smaller x) and north is up (larger y in FITS convention).
    assert positions[0] == positions[1] == (centre - 3, centre + 5)


def test_coadd_is_inverse_variance_weighted_and_ignores_nan():
    a = np.array([[1.0, np.nan]])
    b = np.array([[3.0, 5.0]])
    result, variance = imaging.coadd([a, b], [np.array([[1.0, 1.0]]), np.array([[3.0, 1.0]])])
    assert np.allclose(result, [[1.5, 5.0]])
    assert np.allclose(variance, [[0.75, 1.0]])


def test_coadd_of_all_nan_pixel_is_nan():
    result, variance = imaging.coadd([np.array([[np.nan]])], [np.array([[1.0]])])
    assert np.isnan(result[0, 0]) and np.isnan(variance[0, 0])


def test_png_has_transparent_flagged_pixels_and_is_flipped():
    image = np.array([[0.0, 1.0], [np.nan, 2.0]])  # Row 0 is the bottom in FITS.
    png = Image.open(io.BytesIO(imaging.to_png(image, 0.0, 2.0)))
    pixels = np.array(png)
    assert png.mode == "LA" and pixels.shape == (2, 2, 2)
    assert pixels[0, 0, 1] == 0  # The NaN pixel is now at the top-left, transparent.
    assert pixels[0, 1, 0] == 255 and pixels[1, 0, 0] == 0


def test_fill_enclosed_holes_fills_saturated_cores_only():
    image = np.full((7, 7), 1.0)
    image[3, 3] = image[3, 4] = np.nan  # Saturated core, enclosed.
    image[2, 3] = 50.0
    image[0, 0:3] = np.nan  # Touches the border: no coverage, keep it.
    filled = imaging.fill_enclosed_holes(image)
    assert filled[3, 3] == filled[3, 4] == 50.0
    assert np.isnan(filled[0, 0:3]).all()
    assert np.isnan(image[3, 3])  # The input is not modified.


def test_fill_enclosed_holes_skips_large_holes():
    image = np.full((9, 9), 1.0)
    image[2:7, 2:7] = np.nan  # 25 pixels > max_size
    assert np.isnan(imaging.fill_enclosed_holes(image, max_size=16)[4, 4])


def test_stretch_limits_handle_empty_input():
    assert imaging.stretch_limits([np.array([[np.nan]])]) == (0.0, 1.0)



def test_diff_png_is_red_where_brighter_blue_where_fainter_and_transparent_without_data():
    first = np.array([[0.0, 0.0, 0.0, np.nan]])
    second = np.array([[5.0, -5.0, 0.0, 1.0]])
    data, limit = imaging.to_diff_png(first, second)
    red, _, blue, alpha = np.asarray(Image.open(io.BytesIO(data)))[0].T  # One row, so no flip.
    assert limit > 0
    assert red[0] > 0 and blue[0] == 0
    assert blue[1] > 0 and red[1] == 0
    assert red[2] == blue[2] == 0 and alpha[2] == 255
    assert alpha[3] == 0


def test_colorize_png_maps_grey_to_palette_and_keeps_transparency():
    grey = imaging.to_png(np.array([[0.0, 1.0], [np.nan, 2.0]]), 0.0, 2.0)
    pixels = np.asarray(Image.open(io.BytesIO(imaging.colorize_png(grey, "amber"))))
    # Rows are flipped: PNG row 0 holds the FITS top row [nan, 2.0].
    assert pixels[0, 0, 3] == 0  # NaN stays transparent
    assert tuple(pixels[0, 1]) == (255, 255, 255, 255)  # the brightest pixel is white
    assert tuple(pixels[1, 0]) == (0, 0, 0, 255)  # zero is black
    r, g, b, _ = pixels[1, 1]
    assert r == 255 and 176 < g < 255 and 0 < b < 255  # between amber and white


def test_inferno_palette_runs_from_near_black_to_pale_yellow():
    grey = imaging.to_png(np.array([[0.0, 2.0]]), 0.0, 2.0)
    pixels = np.asarray(Image.open(io.BytesIO(imaging.colorize_png(grey, "inferno"))))[0]
    assert tuple(pixels[0]) == (0, 0, 4, 255) and tuple(pixels[1]) == (252, 255, 164, 255)
