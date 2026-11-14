import pytest

from app import ephemeris


def test_no_motion_at_reference_epoch():
    assert ephemeris.expected_position(10.0, 20.0, 500.0, -300.0, ephemeris.REFERENCE_MJD) == (
        pytest.approx(10.0),
        pytest.approx(20.0),
    )


def test_barnards_star_moves_north_about_10_arcsec_per_year():
    ra, dec = ephemeris.expected_position(
        269.446223, 4.76878, -801.6, 10362.4, ephemeris.REFERENCE_MJD + 365.25
    )
    assert (dec - 4.76878) * 3600 == pytest.approx(10.3624, abs=1e-3)
    assert (ra - 269.446223) * 3600 < 0  # Moves west (RA decreases).
