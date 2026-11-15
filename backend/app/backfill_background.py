"""Fill the local-background columns of ``nasa_sector_exposures`` for rows built before they existed.

The measured spectrum (``GET /patches/{id}/spectrum/measured``) subtracts this sky level from the
raw 3x3 aperture flux, and flags exposures whose light peaks on a neighbour. Each row needs its
cutout again (disk / GCS cache, else IRSA); the stored target pixel, with proper motion already
applied, is reused, so no timeline is rebuilt. Rows are written in batches, so an interrupted run
keeps its progress and a rerun continues where it stopped. Exposures IRSA refuses (503) during
the parallel pass are retried one at a time at the end.

    python -m app.backfill_background               # rows not processed yet
    python -m app.backfill_background --patch 3     # only one patch
    python -m app.backfill_background --workers 2   # fewer parallel downloads (IRSA busy)
    python -m app.backfill_background --all         # recompute every row
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, db, imaging, irsa

BATCH = 48
# Pause before each one-at-a-time retry of an exposure IRSA refused during the parallel pass.
RETRY_PAUSE_S = 2.0

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


def _row_values(row: dict, retries: int = 4) -> tuple | None:
    try:
        data = irsa.fetch_cutout(
            row["uri"], row["cutout_center_ra"], row["cutout_center_dec"], row["cutout_size_deg"],
            retries=retries,
        )
    except RuntimeError as error:  # IRSA busy or down: retried at the end, else left for a rerun.
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


def _save(store, updates: list[tuple]) -> None:
    if updates:
        with store.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(UPDATE_SQL, updates)


def main(
    recompute_all: bool = False, patch_id: int | None = None, workers: int | None = None
) -> None:
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
    done, skipped = 0, []
    with ThreadPoolExecutor(max_workers=workers or config.MAX_PARALLEL_DOWNLOADS) as pool:
        for start in range(0, len(rows), BATCH):
            batch = rows[start : start + BATCH]
            results = list(pool.map(_row_values, batch))
            updates = [u for u in results if u]
            skipped += [row for row, u in zip(batch, results) if u is None]
            _save(store, updates)
            done += len(updates)
            print(f"{min(start + BATCH, len(rows))}/{len(rows)} read, {done} updated", flush=True)
    # IRSA answers 503 at once to bursts of parallel requests (a lone retry usually works), so
    # what was skipped is retried one at a time, slowly, with more patient backoff.
    if skipped:
        print(f"retrying {len(skipped)} skipped exposures one at a time", flush=True)
        for row in skipped:
            time.sleep(RETRY_PAUSE_S)
            value = _row_values(row, retries=6)
            if value:
                _save(store, [value])
                done += 1
    left = len(rows) - done
    print(f"{done} of {len(rows)} updated" + (f"; {left} left for a rerun" if left else ""))


if __name__ == "__main__":
    args = sys.argv[1:]

    def option(name: str) -> int | None:
        return int(args[args.index(name) + 1]) if name in args else None

    main(recompute_all="--all" in args, patch_id=option("--patch"), workers=option("--workers"))
