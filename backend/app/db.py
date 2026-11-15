"""Database connection and setup.

Set up a new database (applies db/schema.sql and seeds the catalogue):

    python -m app.db init
"""

from __future__ import annotations

import sys
import threading

from . import config, ephemeris, gaia, wise
from .science_catalogs import SPHEREX_17_INDICES, SPHEREX_102_CHANNELS
from .store import PostgresStore, Store
from .targets import TARGETS

SCHEMA_PATH = config.BACKEND_DIR / "db" / "schema.sql"

_store: PostgresStore | None = None
_lock = threading.Lock()


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL is empty: the shared PostgreSQL database is not set up yet."""


def get_store() -> PostgresStore:
    """The process-wide PostgresStore, created on first use."""
    global _store
    if not config.DATABASE_URL:
        raise DatabaseNotConfigured("Set DATABASE_URL in backend/.env (see .env.example).")
    with _lock:
        if _store is None:
            _store = PostgresStore(config.DATABASE_URL)
        return _store


def init_database() -> None:
    store = get_store()
    store.apply_schema(SCHEMA_PATH.read_text(encoding="utf-8"))
    store.upsert_targets(TARGETS)
    store.upsert_spherex_channels(SPHEREX_102_CHANNELS)
    store.upsert_spectral_indices(SPHEREX_17_INDICES)


def sync_targets_catalogs(
    store: Store,
    *,
    ref_mjd: float = ephemeris.REFERENCE_MJD,
    match_radius_arcsec: float = 15.0,
) -> dict[str, dict[str, str]]:
    """Hydrate ``targets`` columns from Gaia DR3 (optical) and CatWISE2020 (IR).

    Cold brown dwarfs (``wise-0855``, ``eps-indi-b``) are too faint in visible light for Gaia
    DR3, so they keep their SIMBAD coordinates and only receive CatWISE2020 photometry if matched.
    """
    summary: dict[str, dict[str, str]] = {}
    for target in TARGETS:
        slug = target["slug"]
        ra, dec = float(target["ra"]), float(target["dec"])
        updates: dict[str, object] = {}
        gaia_status = "no_match"
        wise_status = "no_match"

        try:
            g_sources = gaia.query_cone(ra, dec, radius_deg=0.05, g_max=18.0, limit=50)
            best_g = gaia.nearest(g_sources, ra, dec, ref_mjd) if g_sources else None
            if best_g is not None and best_g[1] <= match_radius_arcsec:
                gsrc, gdist = best_g
                prop_ra, prop_dec = gsrc.position_at(ref_mjd)
                updates["ra"] = round(prop_ra, 6)
                updates["dec"] = round(prop_dec, 6)
                if gsrc.pm_ra_mas_yr is not None:
                    updates["pm_ra_mas_yr"] = round(gsrc.pm_ra_mas_yr, 2)
                if gsrc.pm_dec_mas_yr is not None:
                    updates["pm_dec_mas_yr"] = round(gsrc.pm_dec_mas_yr, 2)
                updates["gaia_source_id"] = gsrc.source_id
                updates["gaia_dist_arcsec"] = round(gdist, 3)
                if gsrc.g_mag is not None:
                    updates["gaia_g_mag"] = round(gsrc.g_mag, 3)
                gaia_status = f"matched:{gsrc.source_id}"
        except gaia.GaiaQueryError as err:
            gaia_status = f"error:{err}"

        try:
            w_sources = wise.query_cone(ra, dec, radius_deg=0.05, w2_max=17.5, limit=50)
            best_w = wise.nearest(w_sources, ra, dec, ref_mjd) if w_sources else None
            if best_w is not None and best_w[1] <= match_radius_arcsec:
                wsrc, _ = best_w
                if wsrc.w1_mag is not None:
                    updates["wise_w1_mag"] = round(wsrc.w1_mag, 3)
                if wsrc.w2_mag is not None:
                    updates["wise_w2_mag"] = round(wsrc.w2_mag, 3)
                if wsrc.w1_w2_color is not None:
                    updates["wise_w1_w2_color"] = round(wsrc.w1_w2_color, 3)
                wise_status = f"matched:{wsrc.source_id}"
        except wise.WiseQueryError as err:
            wise_status = f"error:{err}"

        if updates:
            store.update_target_catalog_data(slug, **updates)  # type: ignore[arg-type]
        summary[slug] = {"gaia": gaia_status, "wise": wise_status}
    return summary


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args not in (["init"], ["sync-catalogs"], ["init", "--sync-catalogs"]):
        print("Usage: python -m app.db init [--sync-catalogs] | sync-catalogs", file=sys.stderr)
        return 2
    try:
        if "init" in args:
            init_database()
            print(
                f"Schema applied, {len(TARGETS)} targets, {len(SPHEREX_102_CHANNELS)} channels, "
                f"and {len(SPHEREX_17_INDICES)} spectral indices seeded."
            )
        if "sync-catalogs" in args or "--sync-catalogs" in args:
            summary = sync_targets_catalogs(get_store())
            for slug, info in summary.items():
                print(f"  {slug}: gaia={info['gaia']} wise={info['wise']}")
    except DatabaseNotConfigured as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
