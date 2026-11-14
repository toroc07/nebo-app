"""In-memory Store with the same semantics as PostgresStore, for tests without a database."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app import config
from app.store import EpochImage, ImageInfo, Patch, Timeline, nearest_patch


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.targets: dict[str, dict] = {}
        self.patches: dict[int, Patch] = {}
        self.timelines: dict[int, Timeline] = {}
        self.images: dict[int, tuple[int, EpochImage]] = {}  # id -> (timeline_id, image)
        self._ids = {"patch": 0, "timeline": 0, "image": 0}

    def _next(self, kind: str) -> int:
        self._ids[kind] += 1
        return self._ids[kind]

    def ping(self) -> None:
        pass

    # ----- targets ----------------------------------------------------------------------

    def upsert_targets(self, targets: list[dict]) -> None:
        with self._lock:
            for target in targets:
                self.targets[target["slug"]] = dict(target)

    def list_targets(self) -> list[dict]:
        return sorted(self.targets.values(), key=lambda t: t["name"])

    def get_target(self, slug: str) -> dict | None:
        return self.targets.get(slug)

    # ----- patches ----------------------------------------------------------------------

    def find_patch_near(self, ra: float, dec: float, radius_deg: float) -> Patch | None:
        return nearest_patch(list(self.patches.values()), ra, dec, radius_deg)

    def find_patch_for_target(self, slug: str) -> Patch | None:
        matches = [p for p in self.patches.values() if p.target_slug == slug]
        return min(matches, key=lambda p: p.id) if matches else None

    def create_patch(self, ra: float, dec: float, target_slug: str | None) -> Patch:
        with self._lock:
            patch = Patch(self._next("patch"), ra, dec, target_slug)
            self.patches[patch.id] = patch
            return patch

    def list_patches_with_data(self) -> list[dict]:
        rows = []
        for patch in sorted(self.patches.values(), key=lambda p: p.id):
            ready = sorted(
                t.detector
                for t in self.timelines.values()
                if t.patch_id == patch.id and t.status == "ready"
            )
            if ready:
                rows.append(
                    {"id": patch.id, "ra": patch.ra, "dec": patch.dec,
                     "target_slug": patch.target_slug, "detectors_ready": ready}
                )
        return rows

    # ----- timelines --------------------------------------------------------------------

    def get_timeline(self, patch_id: int, detector: int) -> Timeline | None:
        for timeline in self.timelines.values():
            if timeline.patch_id == patch_id and timeline.detector == detector:
                return timeline
        return None

    def claim_timeline(self, patch_id: int, detector: int) -> Timeline | None:
        with self._lock:
            existing = self.get_timeline(patch_id, detector)
            now = _now()
            if existing is None:
                timeline = Timeline(
                    self._next("timeline"), patch_id, detector, "building", "queued",
                    0, 0, None, None, None, now,
                )
            else:
                age = now - existing.updated_at
                stale = existing.status == "building" and age > timedelta(
                    seconds=config.STALE_BUILD_S
                )
                retry = existing.status == "failed" and age > timedelta(
                    seconds=config.FAILED_RETRY_S
                )
                if not (stale or retry):
                    return None
                timeline = replace(
                    existing, status="building", stage="queued", progress_done=0,
                    progress_total=0, error=None, updated_at=now,
                )
            self.timelines[timeline.id] = timeline
            return timeline

    def _update(self, timeline_id: int, **changes) -> None:
        with self._lock:
            self.timelines[timeline_id] = replace(
                self.timelines[timeline_id], updated_at=_now(), **changes
            )

    def update_progress(self, timeline_id: int, stage: str, done: int, total: int) -> None:
        self._update(timeline_id, stage=stage, progress_done=done, progress_total=total)

    def complete_timeline(
        self, timeline_id: int, images: list[EpochImage], frames_found: int, frames_used: int
    ) -> None:
        with self._lock:
            for image_id in [i for i, (t, _) in self.images.items() if t == timeline_id]:
                del self.images[image_id]
            for image in images:
                self.images[self._next("image")] = (timeline_id, image)
        self._update(
            timeline_id, status="ready", stage="done", error=None,
            frames_found=frames_found, frames_used=frames_used,
        )

    def fail_timeline(self, timeline_id: int, error: str) -> None:
        self._update(timeline_id, status="failed", error=error)

    def age_timeline(self, timeline_id: int, seconds: float) -> None:
        """Test helper: pretend the last update happened ``seconds`` ago."""
        with self._lock:
            timeline = self.timelines[timeline_id]
            self.timelines[timeline_id] = replace(
                timeline, updated_at=timeline.updated_at - timedelta(seconds=seconds)
            )

    # ----- images -----------------------------------------------------------------------

    def list_images(self, timeline_id: int, size: str) -> list[ImageInfo]:
        infos = [
            ImageInfo(
                id=image_id, epoch_index=i.epoch_index, size=i.size, start_utc=i.start_utc,
                end_utc=i.end_utc, mid_mjd=i.mid_mjd, frames_available=i.frames_available,
                frames_used=i.frames_used, width_px=i.width_px, height_px=i.height_px,
                display_min=i.display_min, display_max=i.display_max,
            )
            for image_id, (t, i) in self.images.items()
            if t == timeline_id and i.size == size
        ]
        return sorted(infos, key=lambda info: info.epoch_index)

    def get_png(self, image_id: int) -> bytes | None:
        entry = self.images.get(image_id)
        return entry[1].png if entry else None
