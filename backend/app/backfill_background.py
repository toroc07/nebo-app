"""Fill the local-background columns of ``nasa_sector_exposures`` for rows built before they existed.

The measured spectrum (``GET /patches/{id}/spectrum/measured``) subtracts this sky level from the
raw 3x3 aperture flux, and flags exposures whose light peaks on a neighbour. Each row needs its
cutout again (disk / GCS cache, else IRSA); the stored target pixel, with proper motion already
applied, is reused, so no timeline is rebuilt. Rows are written in batches, so an interrupted run
keeps its progress and a rerun continues where it stopped.

    python -m app.backfill_background               # rows not processed yet
    python -m app.backfill_background --patch 3     # only one patch
    python -m app.backfill_background --all         # recompute every row
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor

from . import config, db, imaging, irsa

BATCH = 48

UPDATE_SQL = """
    UPDATE nasa_sector_exposures SET
        local_background_mjy_sr = %s,
        local_background_sigma_mjy_sr = %s,
        local_background_pixels = %s,
        aperture_peak_offset_px = %s
    WHERE id = %s
"""


def measure(data: bytes, ra: float, dec: float, x: float | None, y: float | None) -> tuple:
    """(level, level error, pixels, peak offset) at the stored target pixel; pixels = 0 when the
    annulus has too few valid pixels, so the row is not retried on every run."""
    if x is None or y is None:
        return None, None, 0, None
    cutout = imaging.read_cutout(data, ra, dec)
    background = imaging.local_background(cutout.image, cutout.science_bad, x, y)
    if background is None:
        return None, None, 0, None
    level, error, pixels, sigma = background
    return level, error, pixels, imaging.peak_offset(cutout.image, x, y, level, sigma)


def _row_values(row: dict) -> tuple | None:
    try:
        data = irsa.fetch_cutout(
            row["uri"], row["cutout_center_ra"], row["cutout_center_dec"], row["cutout_size_deg"]
        )
    except RuntimeError as error:  # IRSA down or the file is gone: left for the next run.
        print(f"skip {row['id']}: {error}")
        return None
    try:
        values = measure(
            data, row["cutout_center_ra"], row["cutout_center_dec"],
            row["target_pix_x"], row["target_pix_y"],
        )
    except Exception as error:  # A damaged file must not stop the whole run.
        print(f"skip {row['id']}: unreadable cutout ({error})")
        return None
    return (*values, row["id"])


def main(recompute_all: bool = False, patch_id: int | None = None) -> None:
    store = db.get_store()
    where, params = [], []
    if not recompute_all:
        where.append("local_background_pixels IS NULL")
    if patch_id is not None:
        where.append("patch_id = %s")
        params.append(patch_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with store.pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, uri, cutout_center_ra, cutout_center_dec, cutout_size_deg,"
            f" target_pix_x, target_pix_y FROM nasa_sector_exposures {clause} ORDER BY id",
            params,
        ).fetchall()
    print(f"{len(rows)} exposures to process")
    done = 0
    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_DOWNLOADS) as pool:
        for start in range(0, len(rows), BATCH):
            updates = [u for u in pool.map(_row_values, rows[start : start + BATCH]) if u]
            if updates:
                with store.pool.connection() as conn, conn.cursor() as cur:
                    cur.executemany(UPDATE_SQL, updates)
            done += len(updates)
            print(f"{min(start + BATCH, len(rows))}/{len(rows)} read, {done} updated", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    patch = int(args[args.index("--patch") + 1]) if "--patch" in args else None
    main(recompute_all="--all" in args, patch_id=patch)
