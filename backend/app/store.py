"""Persistence: catalogue targets, sky patches, timelines and their processed PNG images.

``Store`` is the interface the service and API depend on. ``PostgresStore`` is the real
implementation; tests use an in-memory one (tests/memory_store.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import math
from typing import Any, Protocol

import numpy as np

from . import config, imaging, science_catalogs


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
    has_npz: bool = False


class Store(Protocol):
    def ping(self) -> None: ...
    def upsert_targets(self, targets: list[dict]) -> None: ...
    def list_targets(self) -> list[dict]: ...
    def get_target(self, slug: str) -> dict | None: ...
    def find_patch_near(self, ra: float, dec: float, radius_deg: float) -> Patch | None: ...
    def find_patch_for_target(self, slug: str) -> Patch | None: ...
    def get_patch(self, patch_id: int) -> Patch | None: ...
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

    def dequeue_timeline(self) -> tuple[Patch, Timeline] | None:
        """Take one timeline waiting in the queue (building/queued) for a worker, or None.

        Marks it as started so no other worker takes it. Must be atomic across processes.
        """
        ...

    def update_progress(self, timeline_id: int, stage: str, done: int, total: int) -> None: ...
    def save_partial_timeline(
        self,
        timeline_id: int,
        images: list[EpochImage],
        *,
        stage: str,
        done: int,
        total: int,
        frames_found: int,
        frames_used: int,
    ) -> None: ...
    def complete_timeline(
        self,
        timeline_id: int,
        images: list[EpochImage],
        frames_found: int,
        frames_used: int,
        exposures: list[dict[str, Any]] | None = None,
    ) -> None: ...
    def fail_timeline(self, timeline_id: int, error: str) -> None: ...
    def list_images(self, timeline_id: int, size: str) -> list[ImageInfo]: ...
    def get_png(self, image_id: int) -> bytes | None: ...
    def get_npz(self, image_id: int) -> bytes | None: ...

    def upsert_sector_coordinates(
        self, patch_id: int, sectors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...
    def list_sector_coordinates(self, patch_id: int) -> list[dict[str, Any]]: ...

    def delete_timeline_exposures(self, timeline_id: int) -> None: ...
    def save_nasa_sector_exposures(self, exposures: list[dict[str, Any]]) -> int: ...
    def list_nasa_sector_exposures(
        self, patch_id: int, detector: int | None = None
    ) -> list[dict[str, Any]]: ...

    def upsert_spherex_channels(self, channels: list[Any] | tuple[Any, ...]) -> None: ...
    def list_spherex_channels(self) -> list[dict[str, Any]]: ...

    def upsert_spectral_indices(self, indices: list[Any] | tuple[Any, ...]) -> None: ...
    def list_spectral_indices(self) -> list[dict[str, Any]]: ...

    def get_cached_api(self, cache_key: str) -> dict[str, Any] | None: ...
    def set_cached_api(
        self,
        cache_key: str,
        provider: str,
        response_json: dict[str, Any] | list[Any],
        *,
        query_text: str | None = None,
        request_params: dict[str, Any] | None = None,
        row_count: int = 0,
        expires_at: datetime | None = None,
    ) -> None: ...

    def register_gcs_asset(self, asset: dict[str, Any]) -> dict[str, Any]: ...
    def list_gcs_assets(
        self, patch_id: int | None = None, asset_kind: str | None = None
    ) -> list[dict[str, Any]]: ...

    def save_patch_spectrum(
        self,
        patch_id: int,
        epoch_index: int,
        spectrum: dict[str, Any],
        indices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
    def get_patch_spectrum(self, patch_id: int, epoch_index: int = -1) -> dict[str, Any] | None: ...
    def list_patch_spectral_indices(
        self, patch_id: int, epoch_index: int = -1
    ) -> list[dict[str, Any]]: ...

    def save_model1_attribution(
        self, patch_id: int, epoch_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]: ...
    def get_model1_attribution(
        self, patch_id: int, epoch_index: int = -1, model_version: str = "v1"
    ) -> dict[str, Any] | None: ...

    def save_model2_classification(
        self, patch_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]: ...
    def get_model2_classification(
        self, patch_id: int, model_version: str = "v1"
    ) -> dict[str, Any] | None: ...

    def save_model3_forecast(self, patch_id: int, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get_model3_forecast(
        self, patch_id: int, model_version: str = "v1"
    ) -> dict[str, Any] | None: ...

    def save_citizen_vote(
        self,
        patch_id: int,
        epoch_index: int,
        vote: str,
        *,
        voter_token: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]: ...
    def list_citizen_votes(
        self, patch_id: int, epoch_index: int | None = None
    ) -> list[dict[str, Any]]: ...

    def add_chat_message(self, room: str, nickname: str, body: str) -> dict[str, Any]: ...
    def list_chat_messages(
        self, room: str, after_id: int, limit: int, max_age_s: float
    ) -> list[dict[str, Any]]: ...
    def purge_chat_messages(self, max_age_s: float) -> int: ...

    def save_patch_crossmatch(
        self,
        patch_id: int,
        gaia_json: dict[str, Any] | None,
        wise_json: dict[str, Any] | None,
    ) -> None: ...
    def update_target_catalog_data(
        self,
        slug: str,
        *,
        ra: float | None = None,
        dec: float | None = None,
        pm_ra_mas_yr: float | None = None,
        pm_dec_mas_yr: float | None = None,
        gaia_source_id: str | None = None,
        gaia_dist_arcsec: float | None = None,
        gaia_g_mag: float | None = None,
        wise_w1_mag: float | None = None,
        wise_w2_mag: float | None = None,
        wise_w1_w2_color: float | None = None,
    ) -> None: ...


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
    "width_px, height_px, display_min, display_max, (npz IS NOT NULL) AS has_npz"
)


def _clean_float(value: Any) -> float | None:
    if value is None:
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(v) for v in value]
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _row_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if is_dataclass(item):
        return asdict(item)
    raise TypeError(f"Expected dict or dataclass, got {type(item).__name__}")


def _normalize_spectrum_payload(
    patch_id: int, epoch_index: int, spectrum: dict[str, Any]
) -> dict[str, Any]:
    default_waves = [ch.lambda_c_um for ch in science_catalogs.SPHEREX_102_CHANNELS]
    wavelengths = list(spectrum.get("wavelengths_um") or default_waves)
    flux = list(spectrum.get("flux_mjy") or [None] * 102)
    variance = list(spectrum.get("variance_mjy2") or [None] * 102)
    sigma_reported = list(spectrum.get("sigma_reported_mjy") or [None] * 102)
    valid_mask = list(spectrum.get("valid_mask") or [False] * 102)
    hit_counts = list(spectrum.get("channel_hit_counts") or [0] * 102)

    for seq_name, seq in (
        ("wavelengths_um", wavelengths),
        ("flux_mjy", flux),
        ("variance_mjy2", variance),
        ("sigma_reported_mjy", sigma_reported),
        ("valid_mask", valid_mask),
        ("channel_hit_counts", hit_counts),
    ):
        if len(seq) != 102:
            raise ValueError(f"{seq_name} must have length 102, got {len(seq)}")

    norm_waves = [_clean_float(w) or default_waves[i] for i, w in enumerate(wavelengths)]
    norm_flux = [_clean_float(f) for f in flux]
    norm_var = [_clean_float(v) for v in variance]
    norm_sigma: list[float | None] = []
    norm_valid: list[bool] = []
    norm_hits = [int(h or 0) for h in hit_counts]

    for i in range(102):
        channel_id = i + 1
        if channel_id in science_catalogs.BLANK_CHANNELS or norm_flux[i] is None:
            # Golden Rule #1: BLANKCH channels 51 and 52 must NEVER be imputed as 0.0.
            norm_flux[i] = None
            norm_var[i] = None
            norm_sigma.append(None)
            norm_valid.append(False)
            continue

        f_val = norm_flux[i]
        v_val = norm_var[i]
        s_val = _clean_float(sigma_reported[i])
        if s_val is None and f_val is not None:
            stat_sigma = math.sqrt(v_val) if (v_val is not None and v_val >= 0.0) else 0.0
            s_val = science_catalogs.compute_reported_sigma(f_val, stat_sigma)
        norm_sigma.append(s_val)
        norm_valid.append(bool(valid_mask[i]))

    scope = "all_epochs" if epoch_index < 0 else "single_epoch"
    return {
        "patch_id": patch_id,
        "epoch_index": int(epoch_index),
        "spectrum_scope": spectrum.get("spectrum_scope") or scope,
        "wavelengths_um": norm_waves,
        "flux_mjy": norm_flux,
        "variance_mjy2": norm_var,
        "sigma_reported_mjy": norm_sigma,
        "valid_mask": norm_valid,
        "channel_hit_counts": norm_hits,
        "band_coadd_flux_mjy": _sanitize_json(spectrum.get("band_coadd_flux_mjy") or {}),
        "valid_channel_count": int(sum(1 for flag in norm_valid if flag)),
        "blankch_51_is_null": True,
        "blankch_52_is_null": True,
    }


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

    def get_patch(self, patch_id: int) -> Patch | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT id, ra, dec, target_slug FROM patches WHERE id = %s",
                (patch_id,),
            ).fetchone()
        return Patch(**row) if row else None

    def create_patch(self, ra: float, dec: float, target_slug: str | None) -> Patch:
        sectors = imaging.compute_all_sector_coordinates(ra, dec)
        large = next((s for s in sectors if s["size_name"] == "large"), sectors[0])
        corners_summary = {s["size_name"]: s["corners_icrs"] for s in sectors}
        with self.pool.connection() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO patches (
                        ra, dec, target_slug, fetch_size_deg, pixel_scale_arcsec,
                        ra_min_deg, ra_max_deg, dec_min_deg, dec_max_deg, sector_corners_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, ra, dec, target_slug
                    """,
                    (
                        ra,
                        dec,
                        target_slug,
                        config.FETCH_SIZE_DEG,
                        config.PIXEL_SCALE_ARCSEC,
                        large["ra_min_deg"],
                        large["ra_max_deg"],
                        large["dec_min_deg"],
                        large["dec_max_deg"],
                        self._jsonb(corners_summary),
                    ),
                ).fetchone()
                patch = Patch(**row)
                self._upsert_sector_coordinates_conn(conn, patch.id, sectors)
        return patch

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

    def dequeue_timeline(self) -> tuple[Patch, Timeline] | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                f"""
                UPDATE timelines SET stage = 'querying', updated_at = now()
                WHERE id = (SELECT id FROM timelines
                            WHERE status = 'building' AND stage = 'queued'
                            ORDER BY updated_at FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING {TIMELINE_COLUMNS}
                """
            ).fetchone()
            if row is None:
                return None
            patch = conn.execute(
                "SELECT id, ra, dec, target_slug FROM patches WHERE id = %s", (row["patch_id"],)
            ).fetchone()
        return Patch(**patch), Timeline(**row)

    def update_progress(self, timeline_id: int, stage: str, done: int, total: int) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE timelines SET stage = %s, progress_done = %s, progress_total = %s, "
                "updated_at = now() WHERE id = %s",
                (stage, done, total, timeline_id),
            )

    @staticmethod
    def _replace_timeline_images_conn(conn: Any, timeline_id: int, images: list[EpochImage]) -> None:
        conn.execute("DELETE FROM timeline_images WHERE timeline_id = %s", (timeline_id,))
        if not images:
            return
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO timeline_images (
                    timeline_id, epoch_index, size, start_utc, end_utc, mid_mjd,
                    frames_available, frames_used, width_px, height_px,
                    display_min, display_max, png, npz)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        timeline_id, i.epoch_index, i.size, i.start_utc, i.end_utc,
                        i.mid_mjd, i.frames_available, i.frames_used, i.width_px,
                        i.height_px, i.display_min, i.display_max, i.png, i.npz,
                    )
                    for i in images
                ],
            )

    def save_partial_timeline(
        self,
        timeline_id: int,
        images: list[EpochImage],
        *,
        stage: str,
        done: int,
        total: int,
        frames_found: int,
        frames_used: int,
    ) -> None:
        """Persist intermediate rendered images while keeping the timeline in 'building' state."""
        with self.pool.connection() as conn:
            with conn.transaction():
                self._replace_timeline_images_conn(conn, timeline_id, images)
                conn.execute(
                    "UPDATE timelines SET status = 'building', stage = %s, progress_done = %s, "
                    "progress_total = %s, error = NULL, frames_found = %s, frames_used = %s, "
                    "updated_at = now() WHERE id = %s",
                    (stage, done, total, frames_found, frames_used, timeline_id),
                )

    def complete_timeline(
        self,
        timeline_id: int,
        images: list[EpochImage],
        frames_found: int,
        frames_used: int,
        exposures: list[dict[str, Any]] | None = None,
    ) -> None:
        """Swap in the final images and, when given, this build's exposure rows, atomically:
        a failure keeps the previous images and exposures together."""
        with self.pool.connection() as conn:
            with conn.transaction():
                self._replace_timeline_images_conn(conn, timeline_id, images)
                if exposures is not None:
                    conn.execute(
                        "DELETE FROM nasa_sector_exposures WHERE timeline_id = %s", (timeline_id,)
                    )
                    self._save_exposures_conn(conn, exposures)
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

    def get_npz(self, image_id: int) -> bytes | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT npz FROM timeline_images WHERE id = %s", (image_id,)
            ).fetchone()
        return bytes(row["npz"]) if row and row["npz"] is not None else None

    # ----- JSON helper ------------------------------------------------------------------

    @staticmethod
    def _jsonb(value: Any) -> Any:
        from psycopg.types.json import Jsonb

        return Jsonb(_sanitize_json(value))

    # ----- sector_coordinates -----------------------------------------------------------

    def _upsert_sector_coordinates_conn(
        self, conn: Any, patch_id: int, sectors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        sql = """
            INSERT INTO sector_coordinates (
                patch_id, size_name, center_ra_deg, center_dec_deg, side_deg,
                pixel_scale_arcsec, width_px, height_px,
                ra_min_deg, ra_max_deg, dec_min_deg, dec_max_deg,
                corner_nw_ra, corner_nw_dec, corner_ne_ra, corner_ne_dec,
                corner_se_ra, corner_se_dec, corner_sw_ra, corner_sw_dec,
                corners_icrs, footprint_polygon_text, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
            )
            ON CONFLICT (patch_id, size_name) DO UPDATE SET
                center_ra_deg = EXCLUDED.center_ra_deg,
                center_dec_deg = EXCLUDED.center_dec_deg,
                side_deg = EXCLUDED.side_deg,
                pixel_scale_arcsec = EXCLUDED.pixel_scale_arcsec,
                width_px = EXCLUDED.width_px,
                height_px = EXCLUDED.height_px,
                ra_min_deg = EXCLUDED.ra_min_deg,
                ra_max_deg = EXCLUDED.ra_max_deg,
                dec_min_deg = EXCLUDED.dec_min_deg,
                dec_max_deg = EXCLUDED.dec_max_deg,
                corner_nw_ra = EXCLUDED.corner_nw_ra,
                corner_nw_dec = EXCLUDED.corner_nw_dec,
                corner_ne_ra = EXCLUDED.corner_ne_ra,
                corner_ne_dec = EXCLUDED.corner_ne_dec,
                corner_se_ra = EXCLUDED.corner_se_ra,
                corner_se_dec = EXCLUDED.corner_se_dec,
                corner_sw_ra = EXCLUDED.corner_sw_ra,
                corner_sw_dec = EXCLUDED.corner_sw_dec,
                corners_icrs = EXCLUDED.corners_icrs,
                footprint_polygon_text = EXCLUDED.footprint_polygon_text,
                updated_at = now()
            RETURNING id, patch_id, size_name, center_ra_deg, center_dec_deg, side_deg,
                      pixel_scale_arcsec, width_px, height_px,
                      ra_min_deg, ra_max_deg, dec_min_deg, dec_max_deg,
                      corner_nw_ra, corner_nw_dec, corner_ne_ra, corner_ne_dec,
                      corner_se_ra, corner_se_dec, corner_sw_ra, corner_sw_dec,
                      corners_icrs, footprint_polygon_text
        """
        for s in sectors:
            row = conn.execute(
                sql,
                (
                    patch_id,
                    s["size_name"],
                    s["center_ra_deg"],
                    s["center_dec_deg"],
                    s["side_deg"],
                    s["pixel_scale_arcsec"],
                    s["width_px"],
                    s["height_px"],
                    s["ra_min_deg"],
                    s["ra_max_deg"],
                    s["dec_min_deg"],
                    s["dec_max_deg"],
                    s["corner_nw_ra"],
                    s["corner_nw_dec"],
                    s["corner_ne_ra"],
                    s["corner_ne_dec"],
                    s["corner_se_ra"],
                    s["corner_se_dec"],
                    s["corner_sw_ra"],
                    s["corner_sw_dec"],
                    self._jsonb(s["corners_icrs"]),
                    s["footprint_polygon_text"],
                ),
            ).fetchone()
            if row:
                rows.append(row)
        return rows

    def upsert_sector_coordinates(
        self, patch_id: int, sectors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.transaction():
                return self._upsert_sector_coordinates_conn(conn, patch_id, sectors)

    def list_sector_coordinates(self, patch_id: int) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                """
                SELECT id, patch_id, size_name, center_ra_deg, center_dec_deg, side_deg,
                       pixel_scale_arcsec, width_px, height_px,
                       ra_min_deg, ra_max_deg, dec_min_deg, dec_max_deg,
                       corner_nw_ra, corner_nw_dec, corner_ne_ra, corner_ne_dec,
                       corner_se_ra, corner_se_dec, corner_sw_ra, corner_sw_dec,
                       corners_icrs, footprint_polygon_text
                FROM sector_coordinates
                WHERE patch_id = %s
                ORDER BY side_deg
                """,
                (patch_id,),
            ).fetchall()

    # ----- nasa_sector_exposures --------------------------------------------------------

    def delete_timeline_exposures(self, timeline_id: int) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM nasa_sector_exposures WHERE timeline_id = %s", (timeline_id,))

    def save_nasa_sector_exposures(self, exposures: list[dict[str, Any]]) -> int:
        if not exposures:
            return 0
        with self.pool.connection() as conn:
            return self._save_exposures_conn(conn, exposures)

    def _save_exposures_conn(self, conn: Any, exposures: list[dict[str, Any]]) -> int:
        if not exposures:
            return 0
        sql = """
            INSERT INTO nasa_sector_exposures (
                patch_id, timeline_id, detector, epoch_index, uri, release, plane_id,
                energy_bandpassname, nasa_poly_icrs, energy_bounds_lower_m,
                energy_bounds_upper_m, time_exposure_s, mjd_start, mjd_end, mid_mjd,
                cutout_center_ra, cutout_center_dec, cutout_size_deg,
                cutout_corners_icrs, wcs_header_json, target_pix_x, target_pix_y,
                wavelength_um, bandwidth_um, channel_id, zodi_median_mjy_sr,
                target_flux_mjy_sr, target_variance_mjy_sr2,
                aperture_flux_ujy, aperture_sigma_stat_ujy, aperture_sigma_reported_ujy,
                flags_bitmask_center, saturated_near_target, science_bad_fraction,
                clean_pixel_fraction, cutout_url, sha256_hex, local_cache_path, gcs_uri
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (patch_id, detector, uri) DO UPDATE SET
                timeline_id = EXCLUDED.timeline_id,
                epoch_index = EXCLUDED.epoch_index,
                release = EXCLUDED.release,
                plane_id = COALESCE(EXCLUDED.plane_id, nasa_sector_exposures.plane_id),
                nasa_poly_icrs = COALESCE(EXCLUDED.nasa_poly_icrs, nasa_sector_exposures.nasa_poly_icrs),
                energy_bounds_lower_m = COALESCE(EXCLUDED.energy_bounds_lower_m, nasa_sector_exposures.energy_bounds_lower_m),
                energy_bounds_upper_m = COALESCE(EXCLUDED.energy_bounds_upper_m, nasa_sector_exposures.energy_bounds_upper_m),
                time_exposure_s = COALESCE(EXCLUDED.time_exposure_s, nasa_sector_exposures.time_exposure_s),
                cutout_corners_icrs = COALESCE(EXCLUDED.cutout_corners_icrs, nasa_sector_exposures.cutout_corners_icrs),
                wcs_header_json = COALESCE(EXCLUDED.wcs_header_json, nasa_sector_exposures.wcs_header_json),
                target_pix_x = EXCLUDED.target_pix_x,
                target_pix_y = EXCLUDED.target_pix_y,
                wavelength_um = EXCLUDED.wavelength_um,
                bandwidth_um = EXCLUDED.bandwidth_um,
                channel_id = EXCLUDED.channel_id,
                zodi_median_mjy_sr = EXCLUDED.zodi_median_mjy_sr,
                target_flux_mjy_sr = EXCLUDED.target_flux_mjy_sr,
                target_variance_mjy_sr2 = EXCLUDED.target_variance_mjy_sr2,
                aperture_flux_ujy = EXCLUDED.aperture_flux_ujy,
                aperture_sigma_stat_ujy = EXCLUDED.aperture_sigma_stat_ujy,
                aperture_sigma_reported_ujy = EXCLUDED.aperture_sigma_reported_ujy,
                flags_bitmask_center = EXCLUDED.flags_bitmask_center,
                saturated_near_target = EXCLUDED.saturated_near_target,
                science_bad_fraction = EXCLUDED.science_bad_fraction,
                clean_pixel_fraction = EXCLUDED.clean_pixel_fraction,
                cutout_url = COALESCE(EXCLUDED.cutout_url, nasa_sector_exposures.cutout_url),
                sha256_hex = COALESCE(EXCLUDED.sha256_hex, nasa_sector_exposures.sha256_hex),
                local_cache_path = COALESCE(EXCLUDED.local_cache_path, nasa_sector_exposures.local_cache_path),
                gcs_uri = COALESCE(EXCLUDED.gcs_uri, nasa_sector_exposures.gcs_uri)
        """
        params = [
            (
                e["patch_id"],
                e.get("timeline_id"),
                e["detector"],
                e["epoch_index"],
                e["uri"],
                e["release"],
                e.get("plane_id"),
                e["energy_bandpassname"],
                e.get("nasa_poly_icrs"),
                _clean_float(e.get("energy_bounds_lower_m")),
                _clean_float(e.get("energy_bounds_upper_m")),
                _clean_float(e.get("time_exposure_s")),
                e["mjd_start"],
                e["mjd_end"],
                e["mid_mjd"],
                e["cutout_center_ra"],
                e["cutout_center_dec"],
                e["cutout_size_deg"],
                self._jsonb(e["cutout_corners_icrs"]) if e.get("cutout_corners_icrs") is not None else None,
                self._jsonb(e["wcs_header_json"]) if e.get("wcs_header_json") is not None else None,
                _clean_float(e.get("target_pix_x")),
                _clean_float(e.get("target_pix_y")),
                _clean_float(e.get("wavelength_um")),
                _clean_float(e.get("bandwidth_um")),
                e.get("channel_id"),
                _clean_float(e.get("zodi_median_mjy_sr")),
                _clean_float(e.get("target_flux_mjy_sr")),
                _clean_float(e.get("target_variance_mjy_sr2")),
                _clean_float(e.get("aperture_flux_ujy")),
                _clean_float(e.get("aperture_sigma_stat_ujy")),
                _clean_float(e.get("aperture_sigma_reported_ujy")),
                e.get("flags_bitmask_center"),
                e.get("saturated_near_target"),
                _clean_float(e.get("science_bad_fraction")),
                _clean_float(e.get("clean_pixel_fraction")),
                e.get("cutout_url"),
                e.get("sha256_hex"),
                e.get("local_cache_path"),
                e.get("gcs_uri"),
            )
            for e in exposures
        ]
        with conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def list_nasa_sector_exposures(
        self, patch_id: int, detector: int | None = None
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            if detector is None:
                return conn.execute(
                    "SELECT * FROM nasa_sector_exposures WHERE patch_id = %s ORDER BY detector, mjd_start",
                    (patch_id,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM nasa_sector_exposures WHERE patch_id = %s AND detector = %s ORDER BY mjd_start",
                (patch_id, detector),
            ).fetchall()

    # ----- master catalogs (102 channels & 17 spectral indices) -------------------------

    def upsert_spherex_channels(self, channels: list[Any] | tuple[Any, ...]) -> None:
        rows = [_row_to_dict(c) for c in channels]
        sql = """
            INSERT INTO spherex_channels (
                channel_id, band, detector_channel, lambda_c_um, lambda_min_um, lambda_max_um,
                resolving_power_r, resolving_power_unc, is_blankch, tracer_description
            )
            VALUES (
                %(channel_id)s, %(band)s, %(detector_channel)s, %(lambda_c_um)s,
                %(lambda_min_um)s, %(lambda_max_um)s, %(resolving_power_r)s,
                %(resolving_power_unc)s, %(is_blankch)s, %(tracer_description)s
            )
            ON CONFLICT (channel_id) DO UPDATE SET
                band = EXCLUDED.band,
                detector_channel = EXCLUDED.detector_channel,
                lambda_c_um = EXCLUDED.lambda_c_um,
                lambda_min_um = EXCLUDED.lambda_min_um,
                lambda_max_um = EXCLUDED.lambda_max_um,
                resolving_power_r = EXCLUDED.resolving_power_r,
                resolving_power_unc = EXCLUDED.resolving_power_unc,
                is_blankch = EXCLUDED.is_blankch,
                tracer_description = EXCLUDED.tracer_description
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)

    def list_spherex_channels(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute("SELECT * FROM spherex_channels ORDER BY channel_id").fetchall()

    def upsert_spectral_indices(self, indices: list[Any] | tuple[Any, ...]) -> None:
        rows = []
        for idx in indices:
            d = _row_to_dict(idx)
            d["feature_channels"] = list(d.get("feature_channels") or ())
            rows.append(d)
        sql = """
            INSERT INTO spectral_index_definitions (
                index_id, index_code, target_physics, formula_type, feature_channels,
                blue_anchor_channel, red_anchor_channel, band_a, band_b, discriminator_note
            )
            VALUES (
                %(index_id)s, %(index_code)s, %(target_physics)s, %(formula_type)s,
                %(feature_channels)s, %(blue_anchor_channel)s, %(red_anchor_channel)s,
                %(band_a)s, %(band_b)s, %(discriminator_note)s
            )
            ON CONFLICT (index_id) DO UPDATE SET
                index_code = EXCLUDED.index_code,
                target_physics = EXCLUDED.target_physics,
                formula_type = EXCLUDED.formula_type,
                feature_channels = EXCLUDED.feature_channels,
                blue_anchor_channel = EXCLUDED.blue_anchor_channel,
                red_anchor_channel = EXCLUDED.red_anchor_channel,
                band_a = EXCLUDED.band_a,
                band_b = EXCLUDED.band_b,
                discriminator_note = EXCLUDED.discriminator_note
        """
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)

    def list_spectral_indices(self) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT * FROM spectral_index_definitions ORDER BY index_id"
            ).fetchall()

    # ----- external API cache & GCS media registry --------------------------------------

    def get_cached_api(self, cache_key: str) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return conn.execute(
                """
                SELECT cache_key, provider, query_text, request_params, response_json,
                       row_count, created_at, expires_at
                FROM api_query_cache
                WHERE cache_key = %s
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (cache_key,),
            ).fetchone()

    def set_cached_api(
        self,
        cache_key: str,
        provider: str,
        response_json: dict[str, Any] | list[Any],
        *,
        query_text: str | None = None,
        request_params: dict[str, Any] | None = None,
        row_count: int = 0,
        expires_at: datetime | None = None,
    ) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO api_query_cache (
                    cache_key, provider, query_text, request_params, response_json, row_count, expires_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (cache_key) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    query_text = EXCLUDED.query_text,
                    request_params = EXCLUDED.request_params,
                    response_json = EXCLUDED.response_json,
                    row_count = EXCLUDED.row_count,
                    created_at = now(),
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    cache_key,
                    provider,
                    query_text,
                    self._jsonb(request_params or {}),
                    self._jsonb(response_json),
                    row_count,
                    expires_at,
                ),
            )

    def register_gcs_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO gcs_media_assets (
                    asset_kind, patch_id, timeline_id, exposure_uri, bucket, object_name,
                    gcs_uri, local_path, sha256_hex, crc32c, byte_size, content_type
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (gcs_uri) DO UPDATE SET
                    local_path = COALESCE(EXCLUDED.local_path, gcs_media_assets.local_path),
                    sha256_hex = COALESCE(EXCLUDED.sha256_hex, gcs_media_assets.sha256_hex),
                    crc32c = COALESCE(EXCLUDED.crc32c, gcs_media_assets.crc32c),
                    byte_size = COALESCE(EXCLUDED.byte_size, gcs_media_assets.byte_size)
                RETURNING *
                """,
                (
                    asset["asset_kind"],
                    asset.get("patch_id"),
                    asset.get("timeline_id"),
                    asset.get("exposure_uri"),
                    asset["bucket"],
                    asset["object_name"],
                    asset["gcs_uri"],
                    asset.get("local_path"),
                    asset.get("sha256_hex"),
                    asset.get("crc32c"),
                    asset.get("byte_size"),
                    asset.get("content_type", "application/octet-stream"),
                ),
            ).fetchone()
        assert row is not None
        return row

    def list_gcs_assets(
        self, patch_id: int | None = None, asset_kind: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if patch_id is not None:
            clauses.append("patch_id = %s")
            params.append(patch_id)
        if asset_kind is not None:
            clauses.append("asset_kind = %s")
            params.append(asset_kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.pool.connection() as conn:
            return conn.execute(
                f"SELECT * FROM gcs_media_assets {where} ORDER BY id",
                params,
            ).fetchall()

    # ----- patch spectra & 17 spectral indices ------------------------------------------

    def save_patch_spectrum(
        self,
        patch_id: int,
        epoch_index: int,
        spectrum: dict[str, Any],
        indices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        norm = _normalize_spectrum_payload(patch_id, epoch_index, spectrum)
        with self.pool.connection() as conn:
            with conn.transaction():
                row = conn.execute(
                    """
                    INSERT INTO patch_spectra (
                        patch_id, epoch_index, spectrum_scope, wavelengths_um, flux_mjy,
                        variance_mjy2, sigma_reported_mjy, valid_mask, channel_hit_counts,
                        band_coadd_flux_mjy, valid_channel_count, blankch_51_is_null,
                        blankch_52_is_null, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, TRUE, now())
                    ON CONFLICT (patch_id, epoch_index) DO UPDATE SET
                        spectrum_scope = EXCLUDED.spectrum_scope,
                        wavelengths_um = EXCLUDED.wavelengths_um,
                        flux_mjy = EXCLUDED.flux_mjy,
                        variance_mjy2 = EXCLUDED.variance_mjy2,
                        sigma_reported_mjy = EXCLUDED.sigma_reported_mjy,
                        valid_mask = EXCLUDED.valid_mask,
                        channel_hit_counts = EXCLUDED.channel_hit_counts,
                        band_coadd_flux_mjy = EXCLUDED.band_coadd_flux_mjy,
                        valid_channel_count = EXCLUDED.valid_channel_count,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        norm["patch_id"],
                        norm["epoch_index"],
                        norm["spectrum_scope"],
                        norm["wavelengths_um"],
                        norm["flux_mjy"],
                        norm["variance_mjy2"],
                        norm["sigma_reported_mjy"],
                        norm["valid_mask"],
                        norm["channel_hit_counts"],
                        self._jsonb(norm["band_coadd_flux_mjy"]),
                        norm["valid_channel_count"],
                    ),
                ).fetchone()
                assert row is not None
                saved_indices: list[dict[str, Any]] = []
                if indices:
                    for item in indices:
                        val = _clean_float(item.get("value"))
                        unc = _clean_float(item.get("uncertainty"))
                        snr = _clean_float(item.get("snr"))
                        if snr is None and val is not None and unc is not None and unc > 0.0:
                            snr = abs(val) / unc
                        sig3 = bool(item.get("is_significant_3s"))
                        if not item.get("is_significant_3s") and snr is not None:
                            sig3 = snr >= 3.0
                        idx_row = conn.execute(
                            """
                            INSERT INTO patch_spectral_indices (
                                spectrum_id, patch_id, index_code, value, uncertainty, snr,
                                is_significant_3s, is_valid, details_json, computed_at
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                            ON CONFLICT (spectrum_id, index_code) DO UPDATE SET
                                value = EXCLUDED.value,
                                uncertainty = EXCLUDED.uncertainty,
                                snr = EXCLUDED.snr,
                                is_significant_3s = EXCLUDED.is_significant_3s,
                                is_valid = EXCLUDED.is_valid,
                                details_json = EXCLUDED.details_json,
                                computed_at = now()
                            RETURNING *
                            """,
                            (
                                row["id"],
                                patch_id,
                                item["index_code"],
                                val,
                                unc,
                                snr,
                                sig3,
                                bool(item.get("is_valid", val is not None)),
                                self._jsonb(item.get("details_json") or {}),
                            ),
                        ).fetchone()
                        if idx_row:
                            saved_indices.append(idx_row)
                row["indices"] = saved_indices
        return row

    def get_patch_spectrum(self, patch_id: int, epoch_index: int = -1) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM patch_spectra WHERE patch_id = %s AND epoch_index = %s",
                (patch_id, epoch_index),
            ).fetchone()
            if row is None:
                return None
            indices = conn.execute(
                "SELECT * FROM patch_spectral_indices WHERE spectrum_id = %s ORDER BY index_code",
                (row["id"],),
            ).fetchall()
            row["indices"] = indices
            return row

    def list_patch_spectral_indices(
        self, patch_id: int, epoch_index: int = -1
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            return conn.execute(
                """
                SELECT psi.*
                FROM patch_spectral_indices psi
                JOIN patch_spectra ps ON ps.id = psi.spectrum_id
                WHERE psi.patch_id = %s AND ps.epoch_index = %s
                ORDER BY psi.index_code
                """,
                (patch_id, epoch_index),
            ).fetchall()

    # ----- ML Models 1, 2, 3 & citizen votes --------------------------------------------

    def save_model1_attribution(
        self, patch_id: int, epoch_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        version = payload.get("model_version", "v1")
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO ml_model1_attributions (
                    patch_id, epoch_index, feature_vector, predicted_class, temperature_t,
                    probabilities, treeshap_values, citizen_level1, researcher_level2, model_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (patch_id, epoch_index, model_version) DO UPDATE SET
                    feature_vector = EXCLUDED.feature_vector,
                    predicted_class = EXCLUDED.predicted_class,
                    temperature_t = EXCLUDED.temperature_t,
                    probabilities = EXCLUDED.probabilities,
                    treeshap_values = EXCLUDED.treeshap_values,
                    citizen_level1 = EXCLUDED.citizen_level1,
                    researcher_level2 = EXCLUDED.researcher_level2,
                    created_at = now()
                RETURNING *
                """,
                (
                    patch_id,
                    epoch_index,
                    self._jsonb(payload["feature_vector"]),
                    payload["predicted_class"],
                    float(payload.get("temperature_t", 1.0)),
                    self._jsonb(payload["probabilities"]),
                    self._jsonb(payload["treeshap_values"]),
                    self._jsonb(payload["citizen_level1"]),
                    self._jsonb(payload["researcher_level2"]),
                    version,
                ),
            ).fetchone()
        assert row is not None
        return row

    def get_model1_attribution(
        self, patch_id: int, epoch_index: int = -1, model_version: str = "v1"
    ) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM ml_model1_attributions
                WHERE patch_id = %s AND epoch_index = %s AND model_version = %s
                """,
                (patch_id, epoch_index, model_version),
            ).fetchone()

    def save_model2_classification(
        self, patch_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        version = payload.get("model_version", "v1")
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO ml_model2_classifications (
                    patch_id, spectrum_id, predicted_class, best_template_name,
                    template_teff_k, template_log_g, scale_factor_c, scale_sigma_c,
                    chi2_reduced, dof, valid_channels_used, ml_logits,
                    bayesian_posteriors, citizen_level1, researcher_level2, model_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (patch_id, model_version) DO UPDATE SET
                    spectrum_id = EXCLUDED.spectrum_id,
                    predicted_class = EXCLUDED.predicted_class,
                    best_template_name = EXCLUDED.best_template_name,
                    template_teff_k = EXCLUDED.template_teff_k,
                    template_log_g = EXCLUDED.template_log_g,
                    scale_factor_c = EXCLUDED.scale_factor_c,
                    scale_sigma_c = EXCLUDED.scale_sigma_c,
                    chi2_reduced = EXCLUDED.chi2_reduced,
                    dof = EXCLUDED.dof,
                    valid_channels_used = EXCLUDED.valid_channels_used,
                    ml_logits = EXCLUDED.ml_logits,
                    bayesian_posteriors = EXCLUDED.bayesian_posteriors,
                    citizen_level1 = EXCLUDED.citizen_level1,
                    researcher_level2 = EXCLUDED.researcher_level2,
                    created_at = now()
                RETURNING *
                """,
                (
                    patch_id,
                    payload.get("spectrum_id"),
                    payload["predicted_class"],
                    payload.get("best_template_name"),
                    _clean_float(payload.get("template_teff_k")),
                    _clean_float(payload.get("template_log_g")),
                    _clean_float(payload.get("scale_factor_c")),
                    _clean_float(payload.get("scale_sigma_c")),
                    _clean_float(payload.get("chi2_reduced")),
                    payload.get("dof"),
                    payload.get("valid_channels_used"),
                    self._jsonb(payload.get("ml_logits") or {}),
                    self._jsonb(payload["bayesian_posteriors"]),
                    self._jsonb(payload["citizen_level1"]),
                    self._jsonb(payload["researcher_level2"]),
                    version,
                ),
            ).fetchone()
        assert row is not None
        return row

    def get_model2_classification(
        self, patch_id: int, model_version: str = "v1"
    ) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT * FROM ml_model2_classifications WHERE patch_id = %s AND model_version = %s",
                (patch_id, model_version),
            ).fetchone()

    def save_model3_forecast(self, patch_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        version = payload.get("model_version", "v1")
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO ml_model3_forecasts (
                    patch_id, model1_attribution_id, gp_hyperparams, forecast_series,
                    predicted_cone, z_alert, mahalanobis_d2, delta_log_likelihood,
                    alert_triggered, citizen_level1, researcher_level2, model_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (patch_id, model_version) DO UPDATE SET
                    model1_attribution_id = EXCLUDED.model1_attribution_id,
                    gp_hyperparams = EXCLUDED.gp_hyperparams,
                    forecast_series = EXCLUDED.forecast_series,
                    predicted_cone = EXCLUDED.predicted_cone,
                    z_alert = EXCLUDED.z_alert,
                    mahalanobis_d2 = EXCLUDED.mahalanobis_d2,
                    delta_log_likelihood = EXCLUDED.delta_log_likelihood,
                    alert_triggered = EXCLUDED.alert_triggered,
                    citizen_level1 = EXCLUDED.citizen_level1,
                    researcher_level2 = EXCLUDED.researcher_level2,
                    created_at = now()
                RETURNING *
                """,
                (
                    patch_id,
                    payload.get("model1_attribution_id"),
                    self._jsonb(payload["gp_hyperparams"]),
                    self._jsonb(payload["forecast_series"]),
                    self._jsonb(payload["predicted_cone"]),
                    _clean_float(payload.get("z_alert")),
                    _clean_float(payload.get("mahalanobis_d2")),
                    _clean_float(payload.get("delta_log_likelihood")),
                    bool(payload.get("alert_triggered", False)),
                    self._jsonb(payload["citizen_level1"]),
                    self._jsonb(payload["researcher_level2"]),
                    version,
                ),
            ).fetchone()
        assert row is not None
        return row

    def get_model3_forecast(
        self, patch_id: int, model_version: str = "v1"
    ) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT * FROM ml_model3_forecasts WHERE patch_id = %s AND model_version = %s",
                (patch_id, model_version),
            ).fetchone()

    def save_citizen_vote(
        self,
        patch_id: int,
        epoch_index: int,
        vote: str,
        *,
        voter_token: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        with self.pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO citizen_votes (patch_id, epoch_index, vote, voter_token, comment)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (patch_id, epoch_index, vote, voter_token, comment),
            ).fetchone()
        assert row is not None
        return row

    def list_citizen_votes(
        self, patch_id: int, epoch_index: int | None = None
    ) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            if epoch_index is None:
                return conn.execute(
                    "SELECT * FROM citizen_votes WHERE patch_id = %s ORDER BY id",
                    (patch_id,),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM citizen_votes WHERE patch_id = %s AND epoch_index = %s ORDER BY id",
                (patch_id, epoch_index),
            ).fetchall()

    # ----- public chat ------------------------------------------------------------------

    def add_chat_message(self, room: str, nickname: str, body: str) -> dict[str, Any]:
        with self.pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO chat_messages (room, nickname, body) VALUES (%s, %s, %s) "
                "RETURNING id, room, nickname, body, created_at",
                (room, nickname, body),
            ).fetchone()
        assert row is not None
        return row

    def list_chat_messages(
        self, room: str, after_id: int, limit: int, max_age_s: float
    ) -> list[dict[str, Any]]:
        """Messages newer than ``after_id``, oldest first; with ``after_id`` 0, the latest
        ``limit`` ones. Only messages younger than ``max_age_s`` are ever returned."""
        with self.pool.connection() as conn:
            if after_id > 0:
                return conn.execute(
                    "SELECT id, room, nickname, body, created_at FROM chat_messages "
                    "WHERE room = %s AND id > %s "
                    "AND created_at > now() - make_interval(secs => %s) "
                    "ORDER BY id LIMIT %s",
                    (room, after_id, max_age_s, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM (SELECT id, room, nickname, body, created_at FROM chat_messages "
                "WHERE room = %s AND created_at > now() - make_interval(secs => %s) "
                "ORDER BY id DESC LIMIT %s) latest ORDER BY id",
                (room, max_age_s, limit),
            ).fetchall()

    def purge_chat_messages(self, max_age_s: float) -> int:
        with self.pool.connection() as conn:
            cur = conn.execute(
                "DELETE FROM chat_messages WHERE created_at < now() - make_interval(secs => %s)",
                (max_age_s,),
            )
            return cur.rowcount

    def save_patch_crossmatch(
        self,
        patch_id: int,
        gaia_json: dict[str, Any] | None,
        wise_json: dict[str, Any] | None,
    ) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE patches SET gaia_crossmatch_json = %s, wise_crossmatch_json = %s "
                "WHERE id = %s",
                (
                    self._jsonb(gaia_json) if gaia_json is not None else None,
                    self._jsonb(wise_json) if wise_json is not None else None,
                    patch_id,
                ),
            )

    def update_target_catalog_data(
        self,
        slug: str,
        *,
        ra: float | None = None,
        dec: float | None = None,
        pm_ra_mas_yr: float | None = None,
        pm_dec_mas_yr: float | None = None,
        gaia_source_id: str | None = None,
        gaia_dist_arcsec: float | None = None,
        gaia_g_mag: float | None = None,
        wise_w1_mag: float | None = None,
        wise_w2_mag: float | None = None,
        wise_w1_w2_color: float | None = None,
    ) -> None:
        updates: dict[str, Any] = {
            "ra": ra,
            "dec": dec,
            "pm_ra_mas_yr": pm_ra_mas_yr,
            "pm_dec_mas_yr": pm_dec_mas_yr,
            "gaia_source_id": gaia_source_id,
            "gaia_dist_arcsec": gaia_dist_arcsec,
            "gaia_g_mag": gaia_g_mag,
            "wise_w1_mag": wise_w1_mag,
            "wise_w2_mag": wise_w2_mag,
            "wise_w1_w2_color": wise_w1_w2_color,
        }
        fields = [(col, val) for col, val in updates.items() if val is not None]
        if not fields:
            return
        set_clause = ", ".join(f"{col} = %s" for col, _ in fields)
        values = [val for _, val in fields] + [slug]
        with self.pool.connection() as conn:
            conn.execute(f"UPDATE targets SET {set_clause} WHERE slug = %s", values)
