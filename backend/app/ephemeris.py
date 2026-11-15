"""Where a catalogue object is expected to be at a given time, from its proper motion."""

import math

# Catalogue coordinates (targets.py) are propagated to epoch 2026.2 (Julian years from J2000).
REFERENCE_MJD = 51544.5 + (2026.2 - 2000.0) * 365.25


def expected_position(
    ra: float,
    dec: float,
    pm_ra_mas_yr: float,
    pm_dec_mas_yr: float,
    mjd: float,
    ref_mjd: float = REFERENCE_MJD,
) -> tuple[float, float]:
    """(ra, dec) in degrees at ``mjd``. ``pm_ra_mas_yr`` already includes cos(dec).

    ``ra``/``dec`` are the coordinates at ``ref_mjd``: 2026.2 for targets.py, J2016.0 for Gaia.
    """
    years = (mjd - ref_mjd) / 365.25
    new_dec = dec + pm_dec_mas_yr * years / 3.6e6
    new_ra = ra + pm_ra_mas_yr * years / 3.6e6 / math.cos(math.radians(dec))
    return new_ra % 360.0, new_dec
