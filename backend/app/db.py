"""Database connection and setup.

Set up a new database (applies db/schema.sql and seeds the catalogue):

    python -m app.db init
"""

from __future__ import annotations

import sys
import threading

from . import config
from .science_catalogs import SPHEREX_17_INDICES, SPHEREX_102_CHANNELS
from .store import PostgresStore
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


def main(argv: list[str]) -> int:
    if argv[1:] != ["init"]:
        print("Usage: python -m app.db init", file=sys.stderr)
        return 2
    try:
        init_database()
    except DatabaseNotConfigured as error:
        print(error, file=sys.stderr)
        return 1
    print(
        f"Schema applied, {len(TARGETS)} targets, {len(SPHEREX_102_CHANNELS)} channels, "
        f"and {len(SPHEREX_17_INDICES)} spectral indices seeded."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
