"""Persistence: catalogue targets, sky patches, timelines and their processed PNG images.

``Store`` is the interface the service and API depend on. ``PostgresStore`` is the real
implementation; tests use an in-memory one (tests/memory_store.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import numpy as np

from . import config


@dataclass(frozen=True)
class Patch:
    id: int
    ra: float
    dec: float
    target_slug: str | None


@dataclass(frozen=True)
class Timeline:
    id: int
    patch_id: int
    detector: int
    status: str  # "building" | "ready" | "failed"
    stage: str
    progress_done: int
    progress_total: int
    error: str | None
    frames_found: int | None
    frames_used: int | None
    updated_at: datetime


@dataclass(frozen=True)
class EpochImage:
    """A processed image ready to be stored."""

    epoch_index: int
    size: str
    start_utc: datetime
    end_utc: datetime
    mid_mjd: float
    frames_available: int
    frames_used: int
    width_px: int
    height_px: int
    display_min: float
    display_max: float
    png: bytes
    npz: bytes | None = None  # float32 image + variance; only for the largest size.


@dataclass(frozen=True)
class ImageInfo:
    """Stored image metadata, without the PNG bytes."""

    id: int
    epoch_index: int
    size: str
    start_utc: datetime
    end_utc: datetime
    mid_mjd: float
    frames_available: int
    frames_used: int
    width_px: int
    height_px: int
    display_min: float
    display_max: float


class Store(Protocol):
    def ping(self) -> None: ...
    def upsert_targets(self, targets: list[dict]) -> None: ...
    def list_targets(self) -> list[dict]: ...
    def get_target(self, slug: str) -> dict | None: ...
    def find_patch_near(self, ra: float, dec: float, radius_deg: float) -> Patch | None: ...
    def find_patch_for_target(self, slug: str) -> Patch | None: ...
    def create_patch(self, ra: float, dec: float, target_slug: str | None) -> Patch: ...
    def list_patches_with_data(self) -> list[dict]: ...
    def get_timeline(self, patch_id: int, detector: int) -> Timeline | None: ...

    def claim_timeline(self, patch_id: int, detector: int) -> Timeline | None:
        """Create or take over a timeline for building.

        Returns the timeline when the caller must build it: it did not exist, its build went
        stale (no update for ``config.STALE_BUILD_S``) or it failed more than
        ``config.FAILED_RETRY_S`` ago. Returns None when someone else is building it or it is
        already ready. Must be atomic across processes.
        """
        ...

    def update_progress(self, timeline_id: int, stage: str, done: int, total: int) -> None: ...
    def complete_timeline(
        self, timeline_id: int, images: list[EpochImage], frames_found: int, frames_used: int
    ) -> None: ...
    def fail_timeline(self, timeline_id: int, error: str) -> None: ...
    def list_images(self, timeline_id: int, size: str) -> list[ImageInfo]: ...
    def get_png(self, image_id: int) -> bytes | None: ...


def angular_separation_deg(ra1, dec1, ra2, dec2):
    """Great-circle distance in degrees (haversine; inputs in degrees, numpy-friendly)."""
    ra1, dec1, ra2, dec2 = map(np.radians, (ra1, dec1, ra2, dec2))
    a = np.sin((dec2 - dec1) / 2) ** 2 + np.cos(dec1) * np.cos(dec2) * np.sin((ra2 - ra1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))


def nearest_patch(patches: list[Patch], ra: float, dec: float, radius_deg: float) -> Patch | None:
    if not patches:
        return None
    distances = angular_separation_deg(
        np.array([p.ra for p in patches]), np.array([p.dec for p in patches]), ra, dec
    )
    best = int(np.argmin(distances))
    return patches[best] if distances[best] <= radius_deg else None


TARGET_COLUMNS = (
    "slug", "name", "ra", "dec", "kind", "note",
    "pm_ra_mas_yr", "pm_dec_mas_yr", "recommended_detector",
)
TIMELINE_COLUMNS = (
    "id, patch_id, detector, status, stage, progress_done, progress_total, error, "
    "frames_found, frames_used, updated_at"
)
IMAGE_INFO_COLUMNS = (
    "id, epoch_index, size, start_utc, end_utc, mid_mjd, frames_available, frames_used, "
    "width_px, height_px, display_min, display_max"
)


class PostgresStore:
    """PostgreSQL implementation using a psycopg 3 connection pool."""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10) -> None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            # Cloud databases drop idle connections; check before handing one out.
            check=ConnectionPool.check_connection,
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    def ping(self) -> None:
        with self.pool.connection() as conn:
            conn.execute("SELECT 1")

    def apply_schema(self, sql: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(sql)

    # ----- targets ----------------------------------------------------------------------

    def upsert_targets(self, targets: list[dict]) -> None:
        columns = ", ".join(TARGET_COLUMNS)
        placeholders = ", ".join(f"%({c})s" for c in TARGET_COLUMNS)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in TARGET_COLUMNS if c != "slug")
        sql = (
            f"INSERT INTO targets ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT (slug) DO UPDATE SET {updates}"
        )
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, targets)

    def list_targets(self) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                f"SELECT {', '.join(TARGET_COLUMNS)} FROM targets ORDER BY name"
            ).fetchall()

    def get_target(self, slug: str) -> dict | None:
        with self.pool.connection() as conn:
            return conn.execute(
                f"SELECT {', '.join(TARGET_COLUMNS)} FROM targets WHERE slug = %s", (slug,)
            ).fetchone()

    # ----- patches ----------------------------------------------------------------------

    def find_patch_near(self, ra: float, dec: float, radius_deg: float) -> Patch | None:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, ra, dec, target_slug FROM patches WHERE dec BETWEEN %s AND %s",
                (dec - radius_deg, dec + radius_deg),
            ).fetchall()
        return nearest_patch([Patch(**row) for row in rows], ra, dec, radius_deg)

    def find_patch_for_target(self, slug: str) -> Patch | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT id, ra, dec, target_slug FROM patches WHERE target_slug = %s "
                "ORDER BY id LIMIT 1",
                (slug,),
            ).fetchone()
        return Patch(**row) if row else None

    def create_patch(self, ra: float, dec: float, target_slug: str | None) -> Patch:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO patches (ra, dec, target_slug) VALUES (%s, %s, %s) "
                "RETURNING id, ra, dec, target_slug",
                (ra, dec, target_slug),
            ).fetchone()
        return Patch(**row)

    def list_patches_with_data(self) -> list[dict]:
        with self.pool.connection() as conn:
            return conn.execute(
                """
                SELECT p.id, p.ra, p.dec, p.target_slug,
                       array_agg(t.detector ORDER BY t.detector) AS detectors_ready
                FROM patches p
                JOIN timelines t ON t.patch_id = p.id AND t.status = 'ready'
                GROUP BY p.id
                ORDER BY p.id
                """
            ).fetchall()

    # ----- timelines --------------------------------------------------------------------

    def get_timeline(self, patch_id: int, detector: int) -> Timeline | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                f"SELECT {TIMELINE_COLUMNS} FROM timelines WHERE patch_id = %s AND detector = %s",
                (patch_id, detector),
            ).fetchone()
        return Timeline(**row) if row else None

    def claim_timeline(self, patch_id: int, detector: int) -> Timeline | None:
        # One statement, so concurrent requests and processes cannot both win the claim.
        with self.pool.connection() as conn:
            row = conn.execute(
                f"""
                INSERT INTO timelines (patch_id, detector, status, stage)
                VALUES (%(patch_id)s, %(detector)s, 'building', 'queued')
                ON CONFLICT (patch_id, detector) DO UPDATE
                SET status = 'building', stage = 'queued', progress_done = 0,
                    progress_total = 0, error = NULL, updated_at = now()
                WHERE (timelines.status = 'building'
                       AND timelines.updated_at < now() - make_interval(secs => %(stale)s))
                   OR (timelines.status = 'failed'
                       AND timelines.updated_at < now() - make_interval(secs => %(retry)s))
                RETURNING {TIMELINE_COLUMNS}
                """,
                {
                    "patch_id": patch_id,
                    "detector": detector,
                    "stale": config.STALE_BUILD_S,
                    "retry": config.FAILED_RETRY_S,
                },
            ).fetchone()
        return Timeline(**row) if row else None

    def update_progress(self, timeline_id: int, stage: str, done: int, total: int) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE timelines SET stage = %s, progress_done = %s, progress_total = %s, "
                "updated_at = now() WHERE id = %s",
                (stage, done, total, timeline_id),
            )

    def complete_timeline(
        self, timeline_id: int, images: list[EpochImage], frames_found: int, frames_used: int
    ) -> None:
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute("DELETE FROM timeline_images WHERE timeline_id = %s", (timeline_id,))
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO timeline_images (
                            timeline_id, epoch_index, size, start_utc, end_utc, mid_mjd,
                            frames_available, frames_used, width_px, height_px,
                            display_min, display_max, png)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                timeline_id, i.epoch_index, i.size, i.start_utc, i.end_utc,
                                i.mid_mjd, i.frames_available, i.frames_used, i.width_px,
                                i.height_px, i.display_min, i.display_max, i.png,
                            )
                            for i in images
                        ],
                    )
                conn.execute(
                    "UPDATE timelines SET status = 'ready', stage = 'done', error = NULL, "
                    "frames_found = %s, frames_used = %s, updated_at = now() WHERE id = %s",
                    (frames_found, frames_used, timeline_id),
                )

    def fail_timeline(self, timeline_id: int, error: str) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE timelines SET status = 'failed', error = %s, updated_at = now() "
                "WHERE id = %s",
                (error, timeline_id),
            )

    # ----- images -----------------------------------------------------------------------

    def list_images(self, timeline_id: int, size: str) -> list[ImageInfo]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                f"SELECT {IMAGE_INFO_COLUMNS} FROM timeline_images "
                "WHERE timeline_id = %s AND size = %s ORDER BY epoch_index",
                (timeline_id, size),
            ).fetchall()
        return [ImageInfo(**row) for row in rows]

    def get_png(self, image_id: int) -> bytes | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT png FROM timeline_images WHERE id = %s", (image_id,)
            ).fetchone()
        return bytes(row["png"]) if row else None
