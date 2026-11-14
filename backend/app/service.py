"""Builds SPHEREx image timelines (one image per epoch, detector and size) and stores them.

Fetching from IRSA takes from seconds to minutes, so the API starts a build in the background
and answers "building" with progress, which is stored in the database so any process can see
it. Each patch is downloaded once at the largest size; the smaller sizes are central crops.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import numpy as np
from astropy.time import Time

from . import config, imaging, irsa
from .store import EpochImage, ImageInfo, Patch, Store, Timeline

log = logging.getLogger(__name__)

PATCH_MATCH_RADIUS_DEG = config.PATCH_MATCH_RADIUS_ARCSEC / 3600.0


class NoDataError(Exception):
    """No usable SPHEREx image covers the patch with the requested detector."""


class TargetNotFound(Exception):
    pass


class ServiceBusy(Exception):
    """Too many builds are queued in this process; the client should retry later."""


@dataclass(frozen=True)
class TimelineView:
    status: str  # "ready" | "building" | "failed"
    patch: Patch
    detector: int
    timeline: Timeline
    images: list[ImageInfo] = field(default_factory=list)


def group_into_epochs(mjds: list[float], gap_days: float = config.EPOCH_GAP_DAYS) -> list[list[int]]:
    """Split time-sorted observations into epochs wherever the gap exceeds ``gap_days``."""
    groups: list[list[int]] = []
    for index, mjd in enumerate(mjds):
        if not groups or mjd - mjds[groups[-1][-1]] > gap_days:
            groups.append([index])
        else:
            groups[-1].append(index)
    return groups


def select_evenly(indices: list[int], limit: int) -> list[int]:
    """Keep at most ``limit`` items spread across the list (and so across wavelengths)."""
    if len(indices) <= limit:
        return list(indices)
    positions = np.unique(np.rint(np.linspace(0, len(indices) - 1, limit)).astype(int))
    return [indices[p] for p in positions]


def mjd_to_datetime(mjd: float) -> datetime:
    return Time(mjd, format="mjd").to_datetime(timezone=timezone.utc)


@dataclass
class _Processed:
    epoch: int
    image: np.ndarray  # On the large north-up grid.
    variance: np.ndarray


def render_epoch_images(
    records: list[irsa.FrameRecord], epochs: list[list[int]], processed: list[_Processed]
) -> list[EpochImage]:
    """Co-add each epoch on the large grid, crop every size and render the PNGs.

    Display limits are shared by all epochs of one size, so a blink compares like with like.
    """
    coadds: list[tuple[int, np.ndarray]] = []
    for epoch in range(len(epochs)):
        members = [p for p in processed if p.epoch == epoch]
        if members:
            stacked = imaging.coadd([m.image for m in members], [m.variance for m in members])
            coadds.append((epoch, imaging.fill_enclosed_holes(stacked)))

    images: list[EpochImage] = []
    for size, side_deg in config.SIZES_DEG.items():
        side = imaging.grid_pixels(side_deg)
        crops = [(epoch, imaging.crop_center(image, side)) for epoch, image in coadds]
        low, high = imaging.stretch_limits([crop for _, crop in crops])
        for out_index, (epoch, crop) in enumerate(crops):
            mjds = [records[i].mjd_start for i in epochs[epoch]]
            images.append(
                EpochImage(
                    epoch_index=out_index,
                    size=size,
                    start_utc=mjd_to_datetime(min(mjds)),
                    end_utc=mjd_to_datetime(max(mjds)),
                    mid_mjd=float(np.mean(mjds)),
                    frames_available=len(epochs[epoch]),
                    frames_used=sum(1 for p in processed if p.epoch == epoch),
                    width_px=side,
                    height_px=side,
                    display_min=low,
                    display_max=high,
                    png=imaging.to_png(crop, low, high),
                )
            )
    return images


class TimelineService:
    def __init__(
        self,
        store: Store,
        query_frames: Callable[[float, float, int], list[irsa.FrameRecord]] = irsa.query_frames,
        fetch_cutout: Callable[[str, float, float, float], bytes] = irsa.fetch_cutout,
    ) -> None:
        self.store = store
        self._query_frames = query_frames
        self._fetch_cutout = fetch_cutout
        self._patch_lock = threading.Lock()
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._builds = ThreadPoolExecutor(config.MAX_CONCURRENT_BUILDS, thread_name_prefix="build")
        self._downloads = ThreadPoolExecutor(config.MAX_PARALLEL_DOWNLOADS, thread_name_prefix="dl")

    # ----- patches ----------------------------------------------------------------------

    def resolve_patch(
        self, *, ra: float | None = None, dec: float | None = None, target_slug: str | None = None
    ) -> Patch:
        """The stored patch for a catalogue target or a position, created when missing."""
        with self._patch_lock:
            if target_slug is not None:
                target = self.store.get_target(target_slug)
                if target is None:
                    raise TargetNotFound(target_slug)
                return self.store.find_patch_for_target(target_slug) or self.store.create_patch(
                    target["ra"], target["dec"], target_slug
                )
            assert ra is not None and dec is not None
            return self.store.find_patch_near(
                ra, dec, PATCH_MATCH_RADIUS_DEG
            ) or self.store.create_patch(ra, dec, None)

    # ----- timelines --------------------------------------------------------------------

    def timeline(self, patch: Patch, detector: int, size: str) -> TimelineView:
        """Current state of a timeline, starting a background build when needed."""
        current = self.store.get_timeline(patch.id, detector)
        if current is None or current.status != "ready":
            with self._pending_lock:
                if self._pending >= config.MAX_PENDING_BUILDS and (
                    current is None or current.status == "failed"
                ):
                    raise ServiceBusy()
                claimed = self.store.claim_timeline(patch.id, detector)
                if claimed is not None:
                    self._pending += 1
            if claimed is not None:
                self._builds.submit(self._run_queued_build, patch, claimed)
                current = claimed
            else:
                current = self.store.get_timeline(patch.id, detector)
        assert current is not None
        images = self.store.list_images(current.id, size) if current.status == "ready" else []
        return TimelineView(current.status, patch, detector, current, images)

    def build_now(self, patch: Patch, detector: int) -> Timeline | None:
        """Build synchronously (used by the preload command). Skips ready timelines."""
        current = self.store.get_timeline(patch.id, detector)
        if current is not None and current.status == "ready":
            return current
        claimed = self.store.claim_timeline(patch.id, detector)
        if claimed is None:
            return self.store.get_timeline(patch.id, detector)
        self._run_build(patch, claimed)
        return self.store.get_timeline(patch.id, detector)

    # ----- build ------------------------------------------------------------------------

    def _run_queued_build(self, patch: Patch, timeline: Timeline) -> None:
        try:
            self._run_build(patch, timeline)
        finally:
            with self._pending_lock:
                self._pending -= 1

    def _run_build(self, patch: Patch, timeline: Timeline) -> None:
        try:
            self._build(patch, timeline)
        except NoDataError as error:
            self.store.fail_timeline(timeline.id, str(error))
        except Exception as error:  # Reported to the client; details stay in the log.
            log.exception("Timeline build failed: patch %s detector %s", patch.id, timeline.detector)
            self.store.fail_timeline(timeline.id, f"Build failed: {type(error).__name__}")

    def _build(self, patch: Patch, timeline: Timeline) -> None:
        store, timeline_id = self.store, timeline.id
        store.update_progress(timeline_id, "querying", 0, 0)
        records = self._query_frames(patch.ra, patch.dec, timeline.detector)
        if not records:
            raise NoDataError("No SPHEREx images cover this position with this detector yet.")

        epochs = group_into_epochs([record.mjd_start for record in records])
        work = [
            (epoch, records[i])
            for epoch, indices in enumerate(epochs)
            for i in select_evenly(indices, config.MAX_FRAMES_PER_EPOCH)
        ]
        store.update_progress(timeline_id, "downloading", 0, len(work))
        grid_wcs, grid_shape = imaging.make_target_grid(
            patch.ra, patch.dec, config.SIZES_DEG["large"]
        )

        done = 0
        progress_lock = threading.Lock()

        def process(item: tuple[int, irsa.FrameRecord]) -> _Processed | None:
            nonlocal done
            epoch, record = item
            try:
                data = self._fetch_cutout(record.uri, patch.ra, patch.dec, config.FETCH_SIZE_DEG)
                cutout = imaging.read_cutout(data, patch.ra, patch.dec)
                return _Processed(
                    epoch=epoch,
                    image=imaging.reproject_nearest(cutout.image, cutout.wcs, grid_wcs, grid_shape),
                    variance=imaging.reproject_nearest(
                        cutout.variance, cutout.wcs, grid_wcs, grid_shape
                    ),
                )
            except Exception as error:
                log.warning("Skipping frame %s: %s", record.uri, error)
                return None
            finally:
                with progress_lock:
                    done += 1
                    store.update_progress(timeline_id, "downloading", done, len(work))

        processed = [p for p in self._downloads.map(process, work) if p is not None]
        if not processed:
            raise NoDataError("SPHEREx images were found but none could be downloaded.")

        store.update_progress(timeline_id, "rendering", len(work), len(work))
        images = render_epoch_images(records, epochs, processed)
        store.complete_timeline(
            timeline_id, images, frames_found=len(records), frames_used=len(processed)
        )
