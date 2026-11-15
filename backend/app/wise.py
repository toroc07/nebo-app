"""CatWISE2020 infrared sources around a patch, moved to the date of each SPHEREx epoch.

CatWISE2020 combines WISE and NEOWISE all-sky survey data at 3.4 um (W1) and 4.6 um (W2),
providing infrared photometry and proper motions for ~1.89 billion sources. Cold brown dwarfs
(such as WISE 0855 and Epsilon Indi B) are too faint in visible light for Gaia DR3 but are
bright in W2 with very red W1 - W2 colours.

Queries go to the NASA/IPAC IRSA TAP service with requests (CSV output, explicit timeouts),
like gaia.py does for ESA Gaia DR3, and fall back to NOIRLab Astro Data Lab's copy of the
catalogue (``catwise2020.main``) when IRSA does not answer; see tap_fallback.py.

CatWISE2020 gives proper motions in arcsec/yr (WISE 0855: pmra = -7.9, pmdec = 0.5); they are
converted to mas/yr here, like Gaia's.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from dataclasses import dataclass

from . import ephemeris, gaia, tap_fallback

log = logging.getLogger(__name__)

TAP_SYNC_URL = "https://irsa.ipac.caltech.edu/TAP/sync"
# Mirror of CatWISE2020 at NOIRLab Astro Data Lab (same columns; cones via q3c, not CONTAINS).
DATALAB_TAP_SYNC_URL = "https://datalab.noirlab.edu/tap/sync"
# CatWISE2020 proper motions are in arcsec/yr; WiseSource holds mas/yr.
PM_TO_MAS_YR = 1000.0
CATALOG_NAME = "CatWISE2020"
PROVIDER = "catwise2020_tap"
# CatWISE2020 astrometry is referenced to ~2015.4 (MJD ~57155.8).
REF_EPOCH_YEAR = 2015.4
REF_EPOCH_MJD = 51544.5 + (REF_EPOCH_YEAR - 2000.0) * 365.25

DEFAULT_W2_MAX = 17.5
MAX_ROWS = 5000

COLUMNS = (
    "source_id",
    "ra",
    "dec",
    "pmra",
    "pmdec",
    "w1mpro",
    "w2mpro",
    "w1sigmpro",
    "w2sigmpro",
)


@dataclass(frozen=True)
class WiseSource:
    """One CatWISE2020 infrared source. ``pm_ra_mas_yr`` includes cos(dec)."""

    source_id: str
    ra: float
    dec: float
    pm_ra_mas_yr: float | None
    pm_dec_mas_yr: float | None
    w1_mag: float | None
    w2_mag: float | None
    w1_sig: float | None = None
    w2_sig: float | None = None

    @property
    def has_proper_motion(self) -> bool:
        return self.pm_ra_mas_yr is not None and self.pm_dec_mas_yr is not None

    @property
    def pm_total_mas_yr(self) -> float | None:
        if not self.has_proper_motion:
            return None
        return math.hypot(self.pm_ra_mas_yr or 0.0, self.pm_dec_mas_yr or 0.0)

    @property
    def w1_w2_color(self) -> float | None:
        if self.w1_mag is None or self.w2_mag is None:
            return None
        return self.w1_mag - self.w2_mag

    def position_at(self, mjd: float) -> tuple[float, float]:
        """(ra, dec) in degrees at ``mjd``. Sources without proper motion stay put."""
        if not self.has_proper_motion:
            return self.ra, self.dec
        return ephemeris.expected_position(
            self.ra,
            self.dec,
            self.pm_ra_mas_yr or 0.0,
            self.pm_dec_mas_yr or 0.0,
            mjd,
            ref_mjd=REF_EPOCH_MJD,
        )


class WiseQueryError(RuntimeError):
    """The IRSA CatWISE2020 TAP service could not be reached or answered with an error."""


def build_cone_query(
    ra: float, dec: float, radius_deg: float, w2_max: float = DEFAULT_W2_MAX, limit: int = MAX_ROWS
) -> str:
    # All arguments are validated numbers, so formatting them into ADQL is safe.
    return f"""
SELECT TOP {int(limit)} {", ".join(COLUMNS)}
FROM catwise_2020
WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, {radius_deg:.6f})) = 1
  AND w2mpro < {w2_max:.2f}
ORDER BY w2mpro
"""


def build_datalab_cone_query(
    ra: float, dec: float, radius_deg: float, w2_max: float = DEFAULT_W2_MAX, limit: int = MAX_ROWS
) -> str:
    """The same cone on NOIRLab Data Lab, whose database answers cones with q3c."""
    return f"""
SELECT TOP {int(limit)} {", ".join(COLUMNS)}
FROM catwise2020.main
WHERE 't' = q3c_radial_query(ra, dec, {ra:.7f}, {dec:.7f}, {radius_deg:.6f})
  AND w2mpro < {w2_max:.2f}
ORDER BY w2mpro
"""


def _opt_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _mas_yr(value: str | None) -> float | None:
    arcsec_yr = _opt_float(value)
    return None if arcsec_yr is None else arcsec_yr * PM_TO_MAS_YR


def parse_csv(text: str) -> list[WiseSource]:
    """Rows of an IRSA TAP CSV answer. Empty cells become None."""
    sources = []
    for row in csv.DictReader(io.StringIO(text)):
        ra, dec = _opt_float(row.get("ra")), _opt_float(row.get("dec"))
        source_id = (row.get("source_id") or "").strip()
        if ra is None or dec is None or not source_id:
            continue
        sources.append(
            WiseSource(
                source_id=source_id,
                ra=ra,
                dec=dec,
                pm_ra_mas_yr=_mas_yr(row.get("pmra")),
                pm_dec_mas_yr=_mas_yr(row.get("pmdec")),
                w1_mag=_opt_float(row.get("w1mpro")),
                w2_mag=_opt_float(row.get("w2mpro")),
                w1_sig=_opt_float(row.get("w1sigmpro")),
                w2_sig=_opt_float(row.get("w2sigmpro")),
            )
        )
    return sources


def query_cone(
    ra: float, dec: float, radius_deg: float, w2_max: float = DEFAULT_W2_MAX, limit: int = MAX_ROWS
) -> list[WiseSource]:
    """CatWISE2020 sources within ``radius_deg`` of (ra, dec), brightest in W2 first (IRSA, else
    NOIRLab Data Lab). A 200 answer that is not a CSV table (IRSA's HTML or VOTable error page)
    counts as a failure: read as CSV it would be "no sources" and get cached for good."""
    services = [
        tap_fallback.Service(
            "IRSA CatWISE",
            TAP_SYNC_URL,
            {"QUERY": build_cone_query(ra, dec, radius_deg, w2_max, limit), "FORMAT": "csv"},
        ),
        tap_fallback.Service(
            "NOIRLab CatWISE",
            DATALAB_TAP_SYNC_URL,
            {
                "REQUEST": "doQuery",
                "LANG": "ADQL",
                "FORMAT": "csv",
                "QUERY": build_datalab_cone_query(ra, dec, radius_deg, w2_max, limit),
            },
        ),
    ]
    try:
        return tap_fallback.query(services, parse_csv, header=COLUMNS[0])
    except tap_fallback.TapUnavailable as error:
        raise WiseQueryError(f"CatWISE2020 archive unavailable: {error}") from error


def nearest(
    sources: list[WiseSource], ra: float, dec: float, mjd: float
) -> tuple[WiseSource, float] | None:
    """Closest CatWISE2020 source to (ra, dec) once every source is moved to ``mjd``, with distance (")."""
    best: tuple[WiseSource, float] | None = None
    for source in sources:
        sra, sdec = source.position_at(mjd)
        dist = gaia.separation_arcsec(ra, dec, sra, sdec)
        if best is None or dist < best[1]:
            best = (source, dist)
    return best
