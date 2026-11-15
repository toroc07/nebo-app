"""Builds SPHEREx image timelines (one image per epoch, detector and size) and stores them.

Fetching from IRSA takes from seconds to minutes, so the API starts a build in the background
and answers "building" with progress, which is stored in the database so any process can see
it. Each patch is downloaded once at the largest size; the smaller sizes are central crops.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import requests
from astropy.time import Time

from . import config, ephemeris, imaging, irsa, science_catalogs
from .store import EpochImage, ImageInfo, Patch, Store, Timeline, angular_separation_deg

log = logging.getLogger(__name__)

PATCH_MATCH_RADIUS_DEG = config.PATCH_MATCH_RADIUS_ARCSEC / 3600.0
J2000_MJD = 51544.5
# Every half Julian year from 1990 to 2027: where catalogue coordinates of moving objects may come from.
TRACK_MJDS = [J2000_MJD + (year - 2000.0) * 365.25 for year in np.arange(1990.0, 2027.01, 0.5)]


# Stored as the timeline error when IRSA itself fails (TAP and SIA both down), so clients can
# tell an archive outage from a field without data.
ARCHIVE_UNAVAILABLE = "NASA/IPAC IRSA did not answer. Try again in a few minutes."


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


def split_into_epochs(
    mjds: list[float],
    gap_days: float = config.EPOCH_GAP_DAYS,
    max_span_days: float = config.EPOCH_MAX_SPAN_DAYS,
    min_frames: int = config.MIN_FRAMES_PER_EPOCH,
) -> list[list[int]]:
    """Epochs of time-sorted observations: passes split on ``gap_days``, long passes cut into
    spans of ``max_span_days``, and spans under ``min_frames`` folded into a neighbour."""
    epochs: list[list[int]] = []
    for observing_pass in group_into_epochs(mjds, gap_days):
        spans: list[list[int]] = []
        for index in observing_pass:
            if spans and mjds[index] - mjds[spans[-1][0]] < max_span_days:
                spans[-1].append(index)
            else:
                spans.append([index])
        epochs += _fold_small_spans(spans, mjds, min_frames)
    return epochs


def _fold_small_spans(spans: list[list[int]], mjds: list[float], min_frames: int) -> list[list[int]]:
    """Merge each span with fewer than ``min_frames`` into its closest neighbour in time."""
    spans = [list(span) for span in spans]
    while len(spans) > 1:
        small = next((k for k, span in enumerate(spans) if len(span) < min_frames), None)
        if small is None:
            break
        before = mjds[spans[small][0]] - mjds[spans[small - 1][-1]] if small > 0 else math.inf
        after = (
            mjds[spans[small + 1][0]] - mjds[spans[small][-1]]
            if small < len(spans) - 1
            else math.inf
        )
        # Closest in time; on a tie the smaller neighbour, so the epochs stay balanced.
        if before == after:
            first = small - 1 if len(spans[small - 1]) <= len(spans[small + 1]) else small
        else:
            first = small - 1 if before < after else small
        spans[first] = spans[first] + spans[first + 1]  # Adjacent and sorted: still in order.
        del spans[first + 1]
    return spans


def select_evenly(indices: list[int], limit: int) -> list[int]:
    """Keep at most ``limit`` items spread across the list (and so across wavelengths)."""
    if len(indices) <= limit:
        return list(indices)
    positions = np.unique(np.rint(np.linspace(0, len(indices) - 1, limit)).astype(int))
    return [indices[p] for p in positions]


def plan_progressive_waves(
    epochs: list[list[int]], limit: int = config.MAX_FRAMES_PER_EPOCH
) -> list[tuple[str, list[tuple[int, int]]]]:
    """Order frame downloads from lightest to complete for coordinate searches.

    - Wave 0 ('first_light'): 1 single frame from the first non-empty epoch so a static
      preview image can be rendered and stored within a few seconds.
    - Wave 1 ('preview_ready'): 1 frame from each remaining epoch (breadth-first) so all
      epochs can be blinked quickly.
    - Waves 2..K ('refining'): round-robin across epochs for frames 2..limit, progressively
      improving SNR via inverse-variance co-addition.
    """
    selected = [select_evenly(indices, limit) for indices in epochs]
    waves: list[tuple[str, list[tuple[int, int]]]] = []

    first_epoch = next((e for e, idxs in enumerate(selected) if idxs), None)
    if first_epoch is None:
        return waves

    waves.append(("first_light", [(first_epoch, selected[first_epoch][0])]))

    wave1 = [
        (epoch, idxs[0])
        for epoch, idxs in enumerate(selected)
        if epoch != first_epoch and idxs
    ]
    if wave1:
        waves.append(("preview_ready", wave1))

    max_depth = max((len(idxs) for idxs in selected), default=0)
    for depth in range(1, max_depth):
        wave_r = [
            (epoch, idxs[depth])
            for epoch, idxs in enumerate(selected)
            if depth < len(idxs)
        ]
        if wave_r:
            waves.append(("refining", wave_r))

    return waves


def mjd_to_datetime(mjd: float) -> datetime:
    return Time(mjd, format="mjd").to_datetime(timezone=timezone.utc)


def datetime_to_mjd(moment: datetime) -> float:
    return Time(moment).mjd


@dataclass
class _Processed:
    epoch: int
    image: np.ndarray  # On the large north-up grid.
    variance: np.ndarray
    exposure_row: dict[str, Any] | None = None


def _build_exposure_row(
    patch: Patch,
    timeline: Timeline,
    epoch: int,
    record: irsa.FrameRecord,
    cutout: imaging.Cutout,
    raw_fits: bytes,
    source_position: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Metadata and quick-look photometry of one exposure.

    ``source_position`` is where the catalogue object is at this exposure's time (from its
    proper motion); without it the patch centre is measured. The 3x3 aperture flux is only
    recorded when all its pixels are valid: saturated or flagged pixels would make the sum a
    silent underestimate. It has no aperture correction or local background subtraction, so it
    is a quick-look value, not science-grade photometry.
    """
    url = irsa.cutout_url(record.uri, patch.ra, patch.dec, config.FETCH_SIZE_DEG)
    url_digest = hashlib.sha256(url.encode()).hexdigest()
    sha256_hex = hashlib.sha256(raw_fits).hexdigest()

    ny, nx = cutout.image.shape
    pix_x, pix_y = cutout.target_pix_x, cutout.target_pix_y
    if source_position is not None:
        try:
            pix_x, pix_y = (
                float(v) for v in cutout.wcs.world_to_pixel_values(*source_position)
            )
        except Exception:
            pix_x = pix_y = float("nan")
    target_flux = target_var = None
    aperture_flux_ujy = aperture_sigma_stat_ujy = aperture_sigma_reported_ujy = None

    if math.isfinite(pix_x) and math.isfinite(pix_y):
        ix, iy = int(np.rint(pix_x)), int(np.rint(pix_y))
        if 0 <= iy < ny and 0 <= ix < nx:
            center_f = float(cutout.image[iy, ix])
            center_v = float(cutout.variance[iy, ix])
            if math.isfinite(center_f):
                target_flux = center_f
            if math.isfinite(center_v):
                target_var = center_v

            y0, y1 = max(0, iy - 1), min(ny, iy + 2)
            x0, x1 = max(0, ix - 1), min(nx, ix + 2)
            box_img = cutout.image[y0:y1, x0:x1]
            box_var = cutout.variance[y0:y1, x0:x1]
            box_bad = cutout.science_bad[y0:y1, x0:x1]
            valid_box = (~box_bad) & np.isfinite(box_img) & np.isfinite(box_var) & (box_var >= 0)
            if box_img.shape == (3, 3) and valid_box.all():
                pix_sr = math.radians(config.PIXEL_SCALE_ARCSEC / 3600.0) ** 2
                scale_ujy = pix_sr * 1e12
                flux_mjy_sr = float(np.sum(box_img[valid_box]))
                stat_mjy_sr = float(math.sqrt(np.sum(box_var[valid_box])))
                aperture_flux_ujy = flux_mjy_sr * scale_ujy
                aperture_sigma_stat_ujy = stat_mjy_sr * scale_ujy
                aperture_sigma_reported_ujy = science_catalogs.compute_reported_sigma(
                    aperture_flux_ujy, aperture_sigma_stat_ujy
                )

    mid_mjd = (
        0.5 * (record.mjd_start + record.mjd_end)
        if record.mjd_end > 0.0 and record.mjd_end >= record.mjd_start
        else record.mjd_start
    )
    return {
        "patch_id": patch.id,
        "timeline_id": timeline.id,
        "detector": timeline.detector,
        "epoch_index": epoch,
        "uri": record.uri,
        "release": record.release,
        "plane_id": record.plane_id,
        "energy_bandpassname": irsa.bandpass_name(timeline.detector),
        "nasa_poly_icrs": record.nasa_poly_icrs,
        "energy_bounds_lower_m": record.energy_bounds_lower_m,
        "energy_bounds_upper_m": record.energy_bounds_upper_m,
        "time_exposure_s": record.time_exposure_s,
        "mjd_start": record.mjd_start,
        "mjd_end": record.mjd_end,
        "mid_mjd": mid_mjd,
        "cutout_center_ra": patch.ra,
        "cutout_center_dec": patch.dec,
        "cutout_size_deg": config.FETCH_SIZE_DEG,
        "cutout_corners_icrs": cutout.corners_icrs or None,
        "wcs_header_json": cutout.wcs_header_dict or None,
        "target_pix_x": pix_x,
        "target_pix_y": pix_y,
        "wavelength_um": cutout.wavelength_um,
        "bandwidth_um": cutout.bandwidth_um,
        "channel_id": science_catalogs.channel_for_wavelength(
            timeline.detector, cutout.wavelength_um
        ),
        "zodi_median_mjy_sr": cutout.zodi_median,
        "target_flux_mjy_sr": target_flux,
        "target_variance_mjy_sr2": target_var,
        "aperture_flux_ujy": aperture_flux_ujy,
        "aperture_sigma_stat_ujy": aperture_sigma_stat_ujy,
        "aperture_sigma_reported_ujy": aperture_sigma_reported_ujy,
        "flags_bitmask_center": cutout.flags_center,
        "saturated_near_target": (
            imaging.saturated_near(cutout.saturated, pix_x, pix_y)
            if cutout.saturated is not None
            else None
        ),
        "science_bad_fraction": cutout.science_bad_fraction,
        "clean_pixel_fraction": cutout.clean_pixel_fraction,
        "cutout_url": url,
        "sha256_hex": sha256_hex,
        "local_cache_path": f"cutouts/{url_digest[:2]}/{url_digest}.fits",
        "gcs_uri": None,
    }


def render_epoch_images(
    records: list[irsa.FrameRecord],
    epochs: list[list[int]],
    processed: list[_Processed],
    final: bool = True,
) -> list[EpochImage]:
    """Co-add each epoch on the large grid, crop every size and render the PNGs.

    ``final=False`` is for the previews saved mid-build: it skips the npz and the hole fill.

    Display limits are shared by all epochs and sizes, so a blink compares like with like.
    """
    coadds: list[tuple[int, np.ndarray, bytes]] = []
    for epoch in range(len(epochs)):
        members = [p for p in processed if p.epoch == epoch]
        if members:
            frames, variances = [m.image for m in members], [m.variance for m in members]
            stacked, stacked_variance = imaging.coadd(frames, variances)
            npz = imaging.to_npz(stacked, stacked_variance) if final else None
            coadds.append((epoch, imaging.fill_enclosed_holes(stacked) if final else stacked, npz))

    # One stretch for every size (taken from the largest), so changing size keeps the contrast.
    largest = max(config.SIZES_DEG, key=config.SIZES_DEG.get)
    side = imaging.grid_pixels(config.SIZES_DEG[largest])
    low, high = imaging.stretch_limits([imaging.crop_center(c[1], side) for c in coadds])

    images: list[EpochImage] = []
    for size, side_deg in config.SIZES_DEG.items():
        side = imaging.grid_pixels(side_deg)
        for out_index, (epoch, image, npz) in enumerate(coadds):
            crop = imaging.crop_center(image, side)
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
                    npz=npz if size == largest else None,
                )
            )
    return images


PROGRESS_WRITE_MIN_S = 0.5


class TimelineService:
    def __init__(
        self,
        store: Store,
        query_frames: Callable[[float, float, int], list[irsa.FrameRecord]] = irsa.query_frames,
        fetch_cutout: Callable[[str, float, float, float], bytes] = irsa.fetch_cutout,
    ) -> None:
        self.store = store
        self._query_frames = query_frames
        self._sleep = time.sleep  # Tests replace it to skip the waits.
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
            if target_slug is None and ra is not None and dec is not None:
                target_slug = self._catalogue_target_near(ra, dec)
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

    def _catalogue_target_near(self, ra: float, dec: float) -> str | None:
        """Slug of a catalogue object whose track passes within the patch match radius of ``ra, dec``.

        Fast movers drift arcminutes from the coordinates people type, and each catalogue gives
        them at its own epoch (SIMBAD J2000, WISE ~2010.5, Gaia J2016), so the whole 1990-2027 track
        is checked; the 0.5 yr step moves even Barnard's Star only ~5".
        """
        for target in self.store.list_targets():
            pm_ra, pm_dec = target.get("pm_ra_mas_yr"), target.get("pm_dec_mas_yr")
            mjds = TRACK_MJDS if pm_ra is not None and pm_dec is not None else [ephemeris.REFERENCE_MJD]
            for mjd in mjds:
                r, d = ephemeris.expected_position(target["ra"], target["dec"], pm_ra or 0.0, pm_dec or 0.0, mjd)
                if angular_separation_deg(ra, dec, r, d) <= PATCH_MATCH_RADIUS_DEG:
                    return target["slug"]
        return None

    # ----- timelines --------------------------------------------------------------------

    def timeline(self, patch: Patch, detector: int, size: str) -> TimelineView:
        """Current state of a timeline, starting a background build when needed."""
        current = self.store.get_timeline(patch.id, detector)
        if current is None or current.status != "ready":
            inline = config.BUILD_MODE != "queue"
            with self._pending_lock:
                # shortcut: no backpressure in queue mode, the DB is the queue; add a cap if it grows.
                if inline and self._pending >= config.MAX_PENDING_BUILDS and (
                    current is None or current.status == "failed"
                ):
                    raise ServiceBusy()
                claimed = self.store.claim_timeline(patch.id, detector)
                if claimed is not None and inline:
                    self._pending += 1
            if claimed is not None:
                if inline:
                    self._builds.submit(self._run_queued_build, patch, claimed)
                current = claimed  # In queue mode a worker picks it up (work_one).
            else:
                current = self.store.get_timeline(patch.id, detector)
        assert current is not None
        images = (
            self.store.list_images(current.id, size)
            if current.status == "ready" or current.stage not in ("queued", "querying")
            else []
        )
        return TimelineView(current.status, patch, detector, current, images)

    def work_one(self) -> bool:
        """Build one queued timeline (queue mode). False when nothing is waiting."""
        item = self.store.dequeue_timeline()
        if item is None:
            return False
        self._run_build(*item)
        return True

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

    def rebuild_now(self, patch: Patch, detector: int) -> Timeline | None:
        """Rebuild a timeline synchronously with fresh IRSA data and the current settings.

        A ready timeline stays ready and keeps serving its old images while the new ones are
        built; they are swapped in one transaction. If the rebuild fails the old images stay.
        """
        current = self.store.get_timeline(patch.id, detector)
        if current is None or current.status != "ready":
            return self.build_now(patch, detector)
        try:
            self._build(patch, current, refresh_frames=True)
        except Exception as error:
            log.warning(
                "Rebuild of patch %s detector %s failed, old images kept: %s",
                patch.id, detector, error,
            )
            self.store.update_progress(current.id, "done", 0, 0)
            raise
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
        except requests.RequestException as error:
            log.warning("Timeline build failed, IRSA unavailable: patch %s: %s", patch.id, error)
            self.store.fail_timeline(timeline.id, ARCHIVE_UNAVAILABLE)
        except Exception as error:  # Reported to the client; details stay in the log.
            log.exception("Timeline build failed: patch %s detector %s", patch.id, timeline.detector)
            self.store.fail_timeline(timeline.id, f"Build failed: {type(error).__name__}")

    def _query_frames_patiently(self, patch: Patch, timeline: Timeline) -> list[irsa.FrameRecord]:
        """Query IRSA, waiting out short outages so the visitor never has to press Retry.

        While waiting, the build holds one of the MAX_CONCURRENT_BUILDS threads; the stage
        `waiting_for_archive` (done = attempt) tells the client what is going on.
        """
        # Both the waits and the wall clock count: a failing IRSA query itself can take minutes.
        attempt, waited, start = 0, 0.0, time.monotonic()
        while True:
            try:
                return self._query_frames(patch.ra, patch.dec, timeline.detector)
            except requests.RequestException as error:
                attempt += 1
                wait = 15.0 * 2 ** min(attempt - 1, 2)  # 15, 30, then 60 s
                elapsed = max(waited, time.monotonic() - start)
                if elapsed + wait > config.ARCHIVE_WAIT_S:
                    raise
                waited += wait
                log.warning("IRSA down for timeline %s (attempt %d): %s; retrying in %.0f s", timeline.id, attempt, error, wait)
                self.store.update_progress(timeline.id, "waiting_for_archive", attempt, 0)
                self._sleep(wait)
                self.store.update_progress(timeline.id, "querying", 0, 0)

    def _build(self, patch: Patch, timeline: Timeline, refresh_frames: bool = False) -> None:
        store, timeline_id = self.store, timeline.id
        t0 = time.monotonic()
        store.update_progress(timeline_id, "querying", 0, 0)
        tap_cache_key = hashlib.sha256(
            f"irsa_tap:{patch.ra:.6f}:{patch.dec:.6f}:D{timeline.detector}".encode()
        ).hexdigest()
        records: list[irsa.FrameRecord] | None = None
        if self._query_frames is irsa.query_frames and not refresh_frames:
            cached = store.get_cached_api(tap_cache_key)
            if cached and isinstance(cached.get("response_json"), list):
                records = [irsa.FrameRecord(**item) for item in cached["response_json"]]

        if records is None:
            records = self._query_frames_patiently(patch, timeline)
            if records:
                store.set_cached_api(
                    tap_cache_key,
                    "irsa_spherex_tap",
                    [asdict(r) for r in records],
                    query_text=irsa.build_frames_query(patch.ra, patch.dec, timeline.detector),
                    request_params={
                        "patch_id": patch.id,
                        "ra": patch.ra,
                        "dec": patch.dec,
                        "detector": timeline.detector,
                    },
                    row_count=len(records),
                )

        if not records:
            raise NoDataError("No SPHEREx images cover this position with this detector yet.")

        epochs = split_into_epochs([record.mjd_start for record in records])
        is_progressive = (
            patch.target_slug is None
            and config.PROGRESSIVE_COORDINATE_BUILD
            and not refresh_frames
        )
        if is_progressive:
            waves = plan_progressive_waves(epochs, config.MAX_FRAMES_PER_EPOCH)
            total_work = sum(len(w) for _, w in waves)
        else:
            work = [
                (epoch, records[i])
                for epoch, indices in enumerate(epochs)
                for i in select_evenly(indices, config.MAX_FRAMES_PER_EPOCH)
            ]
            waves = []
            total_work = len(work)

        store.update_progress(timeline_id, "downloading", 0, total_work)
        grid_wcs, grid_shape = imaging.make_target_grid(
            patch.ra, patch.dec, config.SIZES_DEG["large"]
        )

        grid_world = imaging.target_world(grid_wcs, grid_shape)
        done = 0
        last_write = [0.0]
        current_stage = "downloading"
        progress_lock = threading.Lock()

        # Catalogue objects move: measure each exposure where the object is at that time.
        target = store.get_target(patch.target_slug) if patch.target_slug else None
        proper_motion = (
            (target["pm_ra_mas_yr"], target["pm_dec_mas_yr"])
            if target
            and target.get("pm_ra_mas_yr") is not None
            and target.get("pm_dec_mas_yr") is not None
            else None
        )

        def process(item: tuple[int, irsa.FrameRecord]) -> _Processed | None:
            nonlocal done
            epoch, record = item
            try:
                t_fetch = time.monotonic()
                data = self._fetch_cutout(record.uri, patch.ra, patch.dec, config.FETCH_SIZE_DEG)
                log.info("timeline %s: frame in %.1fs", timeline_id, time.monotonic() - t_fetch)
                cutout = imaging.read_cutout(data, patch.ra, patch.dec)
                source_position = (
                    ephemeris.expected_position(
                        patch.ra, patch.dec, *proper_motion, record.mjd_start
                    )
                    if proper_motion
                    else None
                )
                image, variance = imaging.reproject_nearest_many(
                    [cutout.image, cutout.variance], cutout.wcs, grid_wcs, grid_shape, grid_world
                )
                return _Processed(
                    epoch=epoch,
                    image=image,
                    variance=variance,
                    exposure_row=_build_exposure_row(
                        patch, timeline, epoch, record, cutout, data, source_position
                    ),
                )
            except Exception as error:
                log.warning("Skipping frame %s: %s", record.uri, error)
                return None
            finally:
                with progress_lock:
                    done += 1
                    now = time.monotonic()
                    # One DB write per frame is wasteful; the client polls every 2-5 s anyway.
                    if done == total_work or now - last_write[0] >= PROGRESS_WRITE_MIN_S:
                        last_write[0] = now
                        store.update_progress(timeline_id, current_stage, done, total_work)

        if is_progressive:
            store.delete_timeline_exposures(timeline_id)
            processed: list[_Processed] = []

            def submit(items: list[tuple[int, int]]) -> list:
                return [self._downloads.submit(process, (e, records[i])) for e, i in items]

            def collect(futures: list) -> None:
                fresh = [p for p in (f.result() for f in futures) if p is not None]
                processed.extend(fresh)
                rows = [p.exposure_row for p in fresh if p.exposure_row is not None]
                if rows:
                    store.save_nasa_sector_exposures(rows)

            # Every frame is queued up front (first light first, FIFO), so the pool never idles
            # while a wave is rendered and saved: the preview frames download during first
            # light's render. Each wave is saved as soon as its own frames are done, the last
            # preview included, so `preview_ready` is never skipped. The refining frames are
            # rendered once at the end: re-rendering after each round multiplied the build time.
            queued = [(stage, submit(items)) for stage, items in waves]
            for wave_stage, futures in queued:
                if wave_stage == "refining" and processed:
                    current_stage = "refining"
                collect(futures)
                if wave_stage == "refining":
                    continue
                if processed:
                    log.info(
                        "timeline %s: %s at +%.1fs", timeline_id, wave_stage, time.monotonic() - t0
                    )
                    store.save_partial_timeline(
                        timeline_id,
                        render_epoch_images(records, epochs, processed, final=False),
                        stage=wave_stage,
                        done=done,
                        total=total_work,
                        frames_found=len(records),
                        frames_used=len(processed),
                    )
                    current_stage = wave_stage
            if not processed:
                raise NoDataError("SPHEREx images were found but none could be downloaded.")
        else:
            processed = [p for p in self._downloads.map(process, work) if p is not None]
            if not processed:
                raise NoDataError("SPHEREx images were found but none could be downloaded.")

        log.info("timeline %s: all frames at +%.1fs", timeline_id, time.monotonic() - t0)
        store.update_progress(timeline_id, "rendering", total_work, total_work)
        images = render_epoch_images(records, epochs, processed)
        # A rebuild can regroup the epochs, so the exposure rows are replaced in the same
        # transaction as the images; the progressive path saved its rows as it went.
        store.complete_timeline(
            timeline_id,
            images,
            frames_found=len(records),
            frames_used=len(processed),
            exposures=None
            if is_progressive
            else [p.exposure_row for p in processed if p.exposure_row is not None],
        )
