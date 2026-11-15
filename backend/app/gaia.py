"""Gaia DR3 stars around a patch, moved to the date of each SPHEREx epoch.

Gaia measures position, proper motion and parallax for about 1.8 billion stars in visible light.
For the blink viewer it answers "is this source already catalogued?": a change that sits on a
Gaia star is a known object; one that matches nothing is an uncatalogued movement (CLAUDE.md,
"Catalogued objects separate from uncatalogued movements").

Gaia positions are at epoch J2016.0, so every star is propagated with its proper motion to the
epoch's date before it is drawn. Very cold brown dwarfs (WISE 0855, Eps Indi B) are too faint in
visible light to be in Gaia: an infrared source with no Gaia match is expected for them.

Queries go to the ESA Gaia archive TAP service with requests (CSV output, explicit timeouts),
like irsa.py does for IRSA. Cone queries fall back to the GAVO data centre's copy of Gaia DR3
(Heidelberg, ``gaia.dr3lite``) when ESA does not answer; see tap_fallback.py.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from dataclasses import dataclass

from . import ephemeris, tap_fallback

log = logging.getLogger(__name__)

TAP_SYNC_URL = "https://gea.esac.esa.int/tap-server/tap/sync"
# Mirror of Gaia DR3 at the GAVO data centre (Heidelberg): same sources, positions and proper
# motions in ``gaia.dr3lite``; BP-RP is computed from the two magnitudes there.
GAVO_TAP_SYNC_URL = "https://dc.zah.uni-heidelberg.de/tap/sync"
CATALOG_NAME = "Gaia DR3"
PROVIDER = "gaia_dr3_tap"
REF_EPOCH_YEAR = 2016.0
REF_EPOCH_MJD = 51544.5 + (REF_EPOCH_YEAR - 2000.0) * 365.25  # J2016.0 = MJD 57388.5

# SPHEREx pixels are 6.15": stars much fainter than this blend into the background, and a
# 15' patch in the galactic plane holds thousands of them.
DEFAULT_G_MAX = 18.0
# Brightest stars kept per patch. Near the galactic plane even this is reached; the endpoint
# then reports the magnitude down to which the list is complete (g_complete).
MAX_ROWS = 5000

COLUMNS = (
    "source_id",
    "ra",
    "dec",
    "pmra",
    "pmdec",
    "parallax",
    "phot_g_mean_mag",
    "bp_rp",
)


@dataclass(frozen=True)
class GaiaSource:
    """One Gaia DR3 star. Position at J2016.0; ``pm_ra_mas_yr`` already includes cos(dec)."""

    source_id: str
    ra: float
    dec: float
    pm_ra_mas_yr: float | None
    pm_dec_mas_yr: float | None
    parallax_mas: float | None
    g_mag: float | None
    bp_rp: float | None

    @property
    def has_proper_motion(self) -> bool:
        """False for the ~1/5 of Gaia stars with a 2-parameter solution (position only)."""
        return self.pm_ra_mas_yr is not None and self.pm_dec_mas_yr is not None

    @property
    def pm_total_mas_yr(self) -> float | None:
        if not self.has_proper_motion:
            return None
        return math.hypot(self.pm_ra_mas_yr or 0.0, self.pm_dec_mas_yr or 0.0)

    @property
    def distance_pc(self) -> float | None:
        """1000 / parallax, only when the parallax is clearly positive (> 0.1 mas)."""
        if self.parallax_mas is None or self.parallax_mas <= 0.1:
            return None
        return 1000.0 / self.parallax_mas

    def position_at(self, mjd: float) -> tuple[float, float]:
        """(ra, dec) in degrees at ``mjd``. Stars without proper motion stay where they are."""
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


class GaiaQueryError(RuntimeError):
    """The Gaia archive could not be reached or answered with an error."""


def build_cone_query(
    ra: float, dec: float, radius_deg: float, g_max: float = DEFAULT_G_MAX, limit: int = MAX_ROWS
) -> str:
    # All arguments are validated numbers, so formatting them into ADQL is safe.
    return f"""
SELECT TOP {int(limit)} {", ".join(COLUMNS)}
FROM gaiadr3.gaia_source
WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, {radius_deg:.6f}))
  AND phot_g_mean_mag < {g_max:.2f}
ORDER BY phot_g_mean_mag
"""


def build_gavo_cone_query(
    ra: float, dec: float, radius_deg: float, g_max: float = DEFAULT_G_MAX, limit: int = MAX_ROWS
) -> str:
    """The same cone on GAVO's ``gaia.dr3lite`` (same columns, BP-RP from the magnitudes)."""
    return f"""
SELECT TOP {int(limit)} source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag,
  phot_bp_mean_mag - phot_rp_mean_mag AS bp_rp
FROM gaia.dr3lite
WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, {radius_deg:.6f}))
  AND phot_g_mean_mag < {g_max:.2f}
ORDER BY phot_g_mean_mag
"""


def _adql(url: str, name: str, query: str) -> tap_fallback.Service:
    return tap_fallback.Service(
        name, url, {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}
    )


def _opt_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_csv(text: str) -> list[GaiaSource]:
    """Rows of a Gaia TAP CSV answer. Empty cells (no proper motion, no colour) become None."""
    sources = []
    for row in csv.DictReader(io.StringIO(text)):
        ra, dec = _opt_float(row.get("ra")), _opt_float(row.get("dec"))
        source_id = (row.get("source_id") or "").strip()
        if ra is None or dec is None or not source_id:
            continue
        sources.append(
            GaiaSource(
                source_id=source_id,
                ra=ra,
                dec=dec,
                pm_ra_mas_yr=_opt_float(row.get("pmra")),
                pm_dec_mas_yr=_opt_float(row.get("pmdec")),
                parallax_mas=_opt_float(row.get("parallax")),
                g_mag=_opt_float(row.get("phot_g_mean_mag")),
                bp_rp=_opt_float(row.get("bp_rp")),
            )
        )
    return sources


def _ask(services: list[tap_fallback.Service]) -> list[GaiaSource]:
    try:
        return tap_fallback.query(services, parse_csv, header=COLUMNS[0])
    except tap_fallback.TapUnavailable as error:
        raise GaiaQueryError(f"Gaia archive unavailable: {error}") from error


def query_cone(
    ra: float, dec: float, radius_deg: float, g_max: float = DEFAULT_G_MAX, limit: int = MAX_ROWS
) -> list[GaiaSource]:
    """Gaia DR3 stars within ``radius_deg`` of (ra, dec), brightest first (ESA, else GAVO)."""
    return _ask([
        _adql(TAP_SYNC_URL, "ESA Gaia", build_cone_query(ra, dec, radius_deg, g_max, limit)),
        _adql(GAVO_TAP_SYNC_URL, "GAVO Gaia", build_gavo_cone_query(ra, dec, radius_deg, g_max, limit)),
    ])


def build_suggested_query(
    ra: float | None = None,
    dec: float | None = None,
    radius_deg: float = 30.0,
    min_pm_mas_yr: float = 500.0,
    min_parallax_mas: float = 50.0,
    g_max: float = 14.0,
    limit: int = 20,
) -> str:
    """ADQL query for nearby or fast-moving Gaia DR3 stars for the sky explorer."""
    cone = ""
    if ra is not None and dec is not None:
        cone = (
            f"  AND 1 = CONTAINS(POINT('ICRS', ra, dec), "
            f"CIRCLE('ICRS', {ra:.7f}, {dec:.7f}, {radius_deg:.6f}))\n"
        )
    return f"""
SELECT TOP {int(limit)} {", ".join(COLUMNS)}
FROM gaiadr3.gaia_source
WHERE phot_g_mean_mag < {g_max:.2f}
  AND (pm > {min_pm_mas_yr:.1f} OR parallax > {min_parallax_mas:.1f})
{cone}ORDER BY pm DESC
"""


def query_suggested_destinations(
    ra: float | None = None,
    dec: float | None = None,
    radius_deg: float = 30.0,
    min_pm_mas_yr: float = 500.0,
    min_parallax_mas: float = 50.0,
    g_max: float = 14.0,
    limit: int = 20,
) -> list[GaiaSource]:
    """Fetch nearby or high-proper-motion Gaia DR3 stars to suggest in the explorer (ESA only:
    the query needs ESA's ``pm`` column; the endpoint has a curated fallback)."""
    return _ask([_adql(TAP_SYNC_URL, "ESA Gaia", build_suggested_query(
            ra=ra,
            dec=dec,
            radius_deg=radius_deg,
            min_pm_mas_yr=min_pm_mas_yr,
            min_parallax_mas=min_parallax_mas,
            g_max=g_max,
            limit=limit,
        ))])


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angular distance between two ICRS positions (haversine, fine at any scale)."""
    r1, d1, r2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h)))) * 3600.0


def nearest(
    sources: list[GaiaSource], ra: float, dec: float, mjd: float
) -> tuple[GaiaSource, float] | None:
    """Closest Gaia star to (ra, dec) once every star is moved to ``mjd``, with its distance (")."""
    best: tuple[GaiaSource, float] | None = None
    for source in sources:
        sra, sdec = source.position_at(mjd)
        dist = separation_arcsec(ra, dec, sra, sdec)
        if best is None or dist < best[1]:
            best = (source, dist)
    return best
