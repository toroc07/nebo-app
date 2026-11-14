"""Seed catalogue: the test objects named in the challenge.

Coordinates come from SIMBAD and are propagated with their proper motion to epoch 2026.2, the
middle of the SPHEREx data available in November 2026 (2025.6 to 2026.7). Fast movers such as
Barnard's Star and WISE 0855 are several arcminutes away from their J2000 positions, so their
J2000 coordinates would put them outside a small patch.

Keys match the columns of the ``targets`` table (db/schema.sql).
"""

TARGETS = [
    {
        "slug": "barnards-star",
        "name": "Barnard's Star",
        "ra": 269.446223,
        "dec": 4.768780,
        "kind": "high_proper_motion_star",
        "note": "Nearest single red dwarf; moves about 10.4 arcsec per year.",
        "pm_ra_mas_yr": -801.6,
        "pm_dec_mas_yr": 10362.4,
        "recommended_detector": 3,
    },
    {
        "slug": "eps-indi-b",
        "name": "Epsilon Indi B",
        "ra": 331.097073,
        "dec": -56.800786,
        "kind": "brown_dwarf_binary",
        "note": "Pair of T-type brown dwarfs orbiting Epsilon Indi A.",
        "pm_ra_mas_yr": 3982.0,
        "pm_dec_mas_yr": -2466.8,
        "recommended_detector": 6,
    },
    {
        "slug": "wise-0855",
        "name": "WISE 0855-0714",
        "ra": 133.759310,
        "dec": -7.242145,
        "kind": "brown_dwarf",
        "note": (
            "Coldest known brown dwarf; only visible at the longest wavelengths. "
            "About 2 arcmin from the coordinates given in the challenge text."
        ),
        "pm_ra_mas_yr": -8123.7,
        "pm_dec_mas_yr": 673.2,
        "recommended_detector": 6,
    },
    {
        "slug": "rw-aurigae",
        "name": "RW Aurigae",
        "ra": 76.956587,
        "dec": 30.401290,
        "kind": "variable_star",
        "note": "Young T Tauri star with an irregularly dimming disk.",
        "pm_ra_mas_yr": 7.2,
        "pm_dec_mas_yr": -20.3,
        "recommended_detector": 4,
    },
    {
        "slug": "r-draconis",
        "name": "R Draconis",
        "ra": 248.167230,
        "dec": 66.755024,
        "kind": "variable_star",
        "note": "Mira-type pulsating giant with a period of about 245 days.",
        "pm_ra_mas_yr": -20.6,
        "pm_dec_mas_yr": 6.1,
        "recommended_detector": 3,
    },
]
