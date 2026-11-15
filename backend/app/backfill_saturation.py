"""Fill ``nasa_sector_exposures.saturated_near_target`` for rows built before the column existed.

Only the FLAGS extension is needed (the propagated target pixel is already stored), so no
timeline rebuild is required.

    python -m app.backfill_saturation               # NULL rows with a cached cutout
    python -m app.backfill_saturation --download    # also fetch the missing cutouts (GCS / IRSA)
    python -m app.backfill_saturation --all         # recompute every row
"""

from __future__ import annotations

import io
import sys
from concurrent.futures import ThreadPoolExecutor

from astropy.io import fits

from . import config, db, imaging, irsa


def _saturated(data: bytes | str, row: dict) -> bool | None:
    with fits.open(io.BytesIO(data) if isinstance(data, bytes) else data) as hdul:
        flags = hdul["FLAGS"].data.astype("int64")
        mask = imaging.flag_mask(hdul["FLAGS"].header, imaging.SATURATION_FLAG_NAMES)
    return imaging.saturated_near((flags & mask) != 0, row["target_pix_x"], row["target_pix_y"])


def _value(row: dict, download: bool) -> tuple[bool | None, int] | None:
    path = config.CACHE_DIR / (row["local_cache_path"] or "_")
    if path.is_file():
        return _saturated(str(path), row), row["id"]
    if not download:
        return None
    try:
        data = irsa.fetch_cutout(row["uri"], row["ra"], row["dec"], config.FETCH_SIZE_DEG)
    except RuntimeError as error:
        print(f"skip {row['id']}: {error}")
        return None
    return _saturated(data, row), row["id"]


def main(recompute_all: bool = False, download: bool = False) -> None:
    store = db.get_store()
    where = "" if recompute_all else "WHERE e.saturated_near_target IS NULL"
    with store.pool.connection() as conn:
        rows = conn.execute(
            "SELECT e.id, e.uri, e.local_cache_path, e.target_pix_x, e.target_pix_y, p.ra, p.dec"
            f" FROM nasa_sector_exposures e JOIN patches p ON p.id = e.patch_id {where}"
        ).fetchall()
    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_DOWNLOADS if download else 1) as pool:
        results = list(pool.map(lambda r: _value(r, download), rows))
    updates = [r for r in results if r is not None]
    with store.pool.connection() as conn, conn.cursor() as cur:  # one round trip per batch
        cur.executemany(
            "UPDATE nasa_sector_exposures SET saturated_near_target = %s WHERE id = %s", updates
        )
    print(f"updated {len(updates)} of {len(rows)} exposures")


if __name__ == "__main__":
    main(recompute_all="--all" in sys.argv, download="--download" in sys.argv)
