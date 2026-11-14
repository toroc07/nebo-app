"""In-memory Store with the same semantics as PostgresStore, for tests without a database."""

from __future__ import annotations

import copy
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from app import config, imaging, science_catalogs
from app.store import (
    EpochImage,
    ImageInfo,
    Patch,
    Timeline,
    _clean_float,
    _normalize_spectrum_payload,
    _row_to_dict,
    _sanitize_json,
    nearest_patch,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.targets: dict[str, dict] = {}
        self.patches: dict[int, Patch] = {}
        self.timelines: dict[int, Timeline] = {}
        self.images: dict[int, tuple[int, EpochImage]] = {}  # id -> (timeline_id, image)
        self.sector_coordinates: dict[int, dict[str, dict[str, Any]]] = {}
        self.nasa_sector_exposures: dict[tuple[int, int, str], dict[str, Any]] = {}
        self.spherex_channels: dict[int, dict[str, Any]] = {}
        self.spectral_indices: dict[str, dict[str, Any]] = {}
        self.api_query_cache: dict[str, dict[str, Any]] = {}
        self.gcs_media_assets: dict[str, dict[str, Any]] = {}
        self.patch_spectra: dict[tuple[int, int], dict[str, Any]] = {}
        self.patch_spectral_indices: dict[int, dict[str, dict[str, Any]]] = {}
        self.model1_attributions: dict[tuple[int, int, str], dict[str, Any]] = {}
        self.model2_classifications: dict[tuple[int, str], dict[str, Any]] = {}
        self.model3_forecasts: dict[tuple[int, str], dict[str, Any]] = {}
        self.citizen_votes: list[dict[str, Any]] = []
        self._ids = {
            "patch": 0,
            "timeline": 0,
            "image": 0,
            "sector": 0,
            "exposure": 0,
            "gcs": 0,
            "spectrum": 0,
            "idx": 0,
            "m1": 0,
            "m2": 0,
            "m3": 0,
            "vote": 0,
        }

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

    def get_patch(self, patch_id: int) -> Patch | None:
        return self.patches.get(patch_id)

    def create_patch(self, ra: float, dec: float, target_slug: str | None) -> Patch:
        sectors = imaging.compute_all_sector_coordinates(ra, dec)
        with self._lock:
            patch = Patch(self._next("patch"), ra, dec, target_slug)
            self.patches[patch.id] = patch
            self._upsert_sectors_locked(patch.id, sectors)
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

    def dequeue_timeline(self) -> tuple[Patch, Timeline] | None:
        with self._lock:
            queued = sorted(
                (t for t in self.timelines.values() if t.status == "building" and t.stage == "queued"),
                key=lambda t: t.updated_at,
            )
            if not queued:
                return None
            timeline = replace(queued[0], stage="querying", updated_at=_now())
            self.timelines[timeline.id] = timeline
            return self.patches[timeline.patch_id], timeline

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
                has_npz=(i.npz is not None),
            )
            for image_id, (t, i) in self.images.items()
            if t == timeline_id and i.size == size
        ]
        return sorted(infos, key=lambda info: info.epoch_index)

    def get_png(self, image_id: int) -> bytes | None:
        entry = self.images.get(image_id)
        return entry[1].png if entry else None

    def get_npz(self, image_id: int) -> bytes | None:
        entry = self.images.get(image_id)
        return entry[1].npz if entry else None

    # ----- sector_coordinates & nasa_sector_exposures -----------------------------------

    def _upsert_sectors_locked(
        self, patch_id: int, sectors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        bucket = self.sector_coordinates.setdefault(patch_id, {})
        out: list[dict[str, Any]] = []
        for s in sectors:
            size_name = s["size_name"]
            existing = bucket.get(size_name)
            row_id = existing["id"] if existing else self._next("sector")
            row = copy.deepcopy(s) | {"id": row_id, "patch_id": patch_id}
            bucket[size_name] = row
            out.append(copy.deepcopy(row))
        return out

    def upsert_sector_coordinates(
        self, patch_id: int, sectors: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._upsert_sectors_locked(patch_id, sectors)

    def list_sector_coordinates(self, patch_id: int) -> list[dict[str, Any]]:
        bucket = self.sector_coordinates.get(patch_id, {})
        return [copy.deepcopy(r) for r in sorted(bucket.values(), key=lambda x: x["side_deg"])]

    def delete_timeline_exposures(self, timeline_id: int) -> None:
        with self._lock:
            for key in [k for k, r in self.nasa_sector_exposures.items() if r.get("timeline_id") == timeline_id]:
                del self.nasa_sector_exposures[key]

    def save_nasa_sector_exposures(self, exposures: list[dict[str, Any]]) -> int:
        if not exposures:
            return 0
        with self._lock:
            for e in exposures:
                key = (e["patch_id"], e["detector"], e["uri"])
                existing = self.nasa_sector_exposures.get(key)
                row_id = existing["id"] if existing else self._next("exposure")
                row = copy.deepcopy(e) | {"id": row_id}
                self.nasa_sector_exposures[key] = row
        return len(exposures)

    def list_nasa_sector_exposures(
        self, patch_id: int, detector: int | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            copy.deepcopy(r)
            for (pid, det, _), r in self.nasa_sector_exposures.items()
            if pid == patch_id and (detector is None or det == detector)
        ]
        return sorted(rows, key=lambda r: (r["detector"], r["mjd_start"]))

    # ----- master catalogs --------------------------------------------------------------

    def upsert_spherex_channels(self, channels: list[Any] | tuple[Any, ...]) -> None:
        with self._lock:
            for item in channels:
                d = _row_to_dict(item)
                self.spherex_channels[int(d["channel_id"])] = d

    def list_spherex_channels(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(self.spherex_channels[k]) for k in sorted(self.spherex_channels)]

    def upsert_spectral_indices(self, indices: list[Any] | tuple[Any, ...]) -> None:
        with self._lock:
            for item in indices:
                d = _row_to_dict(item)
                d["feature_channels"] = list(d.get("feature_channels") or ())
                self.spectral_indices[d["index_code"]] = d

    def list_spectral_indices(self) -> list[dict[str, Any]]:
        return sorted(
            [copy.deepcopy(v) for v in self.spectral_indices.values()],
            key=lambda x: x["index_id"],
        )

    # ----- API cache & GCS assets -------------------------------------------------------

    def get_cached_api(self, cache_key: str) -> dict[str, Any] | None:
        entry = self.api_query_cache.get(cache_key)
        if entry is None:
            return None
        expires_at = entry.get("expires_at")
        if expires_at is not None and expires_at <= _now():
            return None
        return copy.deepcopy(entry)

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
        with self._lock:
            self.api_query_cache[cache_key] = {
                "cache_key": cache_key,
                "provider": provider,
                "query_text": query_text,
                "request_params": _sanitize_json(request_params or {}),
                "response_json": _sanitize_json(response_json),
                "row_count": row_count,
                "created_at": _now(),
                "expires_at": expires_at,
            }

    def register_gcs_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            uri = asset["gcs_uri"]
            existing = self.gcs_media_assets.get(uri)
            row_id = existing["id"] if existing else self._next("gcs")
            row = copy.deepcopy(asset) | {"id": row_id, "created_at": _now()}
            self.gcs_media_assets[uri] = row
            return copy.deepcopy(row)

    def list_gcs_assets(
        self, patch_id: int | None = None, asset_kind: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            copy.deepcopy(a)
            for a in self.gcs_media_assets.values()
            if (patch_id is None or a.get("patch_id") == patch_id)
            and (asset_kind is None or a.get("asset_kind") == asset_kind)
        ]
        return sorted(rows, key=lambda x: x["id"])

    # ----- patch spectra & 17 indices ---------------------------------------------------

    def save_patch_spectrum(
        self,
        patch_id: int,
        epoch_index: int,
        spectrum: dict[str, Any],
        indices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        norm = _normalize_spectrum_payload(patch_id, epoch_index, spectrum)
        with self._lock:
            key = (patch_id, int(epoch_index))
            existing = self.patch_spectra.get(key)
            spec_id = existing["id"] if existing else self._next("spectrum")
            row = norm | {"id": spec_id, "updated_at": _now()}
            self.patch_spectra[key] = row
            idx_bucket = self.patch_spectral_indices.setdefault(spec_id, {})
            saved_indices: list[dict[str, Any]] = []
            if indices:
                for item in indices:
                    code = item["index_code"]
                    val = _clean_float(item.get("value"))
                    unc = _clean_float(item.get("uncertainty"))
                    snr = _clean_float(item.get("snr"))
                    if snr is None and val is not None and unc is not None and unc > 0.0:
                        snr = abs(val) / unc
                    sig3 = bool(item.get("is_significant_3s"))
                    if not item.get("is_significant_3s") and snr is not None:
                        sig3 = snr >= 3.0
                    prev = idx_bucket.get(code)
                    idx_id = prev["id"] if prev else self._next("idx")
                    idx_row = {
                        "id": idx_id,
                        "spectrum_id": spec_id,
                        "patch_id": patch_id,
                        "index_code": code,
                        "value": val,
                        "uncertainty": unc,
                        "snr": snr,
                        "is_significant_3s": sig3,
                        "is_valid": bool(item.get("is_valid", val is not None)),
                        "details_json": _sanitize_json(item.get("details_json") or {}),
                        "computed_at": _now(),
                    }
                    idx_bucket[code] = idx_row
                    saved_indices.append(copy.deepcopy(idx_row))
            out = copy.deepcopy(row)
            out["indices"] = saved_indices
            return out

    def get_patch_spectrum(self, patch_id: int, epoch_index: int = -1) -> dict[str, Any] | None:
        row = self.patch_spectra.get((patch_id, int(epoch_index)))
        if row is None:
            return None
        out = copy.deepcopy(row)
        idx_bucket = self.patch_spectral_indices.get(row["id"], {})
        out["indices"] = [copy.deepcopy(idx_bucket[k]) for k in sorted(idx_bucket)]
        return out

    def list_patch_spectral_indices(
        self, patch_id: int, epoch_index: int = -1
    ) -> list[dict[str, Any]]:
        spec = self.patch_spectra.get((patch_id, int(epoch_index)))
        if spec is None:
            return []
        idx_bucket = self.patch_spectral_indices.get(spec["id"], {})
        return [copy.deepcopy(idx_bucket[k]) for k in sorted(idx_bucket)]

    # ----- ML Models 1, 2, 3 & citizen votes --------------------------------------------

    def save_model1_attribution(
        self, patch_id: int, epoch_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        version = payload.get("model_version", "v1")
        with self._lock:
            key = (patch_id, int(epoch_index), version)
            existing = self.model1_attributions.get(key)
            row_id = existing["id"] if existing else self._next("m1")
            row = {
                "id": row_id,
                "patch_id": patch_id,
                "epoch_index": int(epoch_index),
                "feature_vector": _sanitize_json(payload["feature_vector"]),
                "predicted_class": payload["predicted_class"],
                "temperature_t": float(payload.get("temperature_t", 1.0)),
                "probabilities": _sanitize_json(payload["probabilities"]),
                "treeshap_values": _sanitize_json(payload["treeshap_values"]),
                "citizen_level1": _sanitize_json(payload["citizen_level1"]),
                "researcher_level2": _sanitize_json(payload["researcher_level2"]),
                "model_version": version,
                "created_at": _now(),
            }
            self.model1_attributions[key] = row
            return copy.deepcopy(row)

    def get_model1_attribution(
        self, patch_id: int, epoch_index: int = -1, model_version: str = "v1"
    ) -> dict[str, Any] | None:
        row = self.model1_attributions.get((patch_id, int(epoch_index), model_version))
        return copy.deepcopy(row) if row else None

    def save_model2_classification(
        self, patch_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        version = payload.get("model_version", "v1")
        with self._lock:
            key = (patch_id, version)
            existing = self.model2_classifications.get(key)
            row_id = existing["id"] if existing else self._next("m2")
            row = {
                "id": row_id,
                "patch_id": patch_id,
                "spectrum_id": payload.get("spectrum_id"),
                "predicted_class": payload["predicted_class"],
                "best_template_name": payload.get("best_template_name"),
                "template_teff_k": _clean_float(payload.get("template_teff_k")),
                "template_log_g": _clean_float(payload.get("template_log_g")),
                "scale_factor_c": _clean_float(payload.get("scale_factor_c")),
                "scale_sigma_c": _clean_float(payload.get("scale_sigma_c")),
                "chi2_reduced": _clean_float(payload.get("chi2_reduced")),
                "dof": payload.get("dof"),
                "valid_channels_used": payload.get("valid_channels_used"),
                "ml_logits": _sanitize_json(payload.get("ml_logits") or {}),
                "bayesian_posteriors": _sanitize_json(payload["bayesian_posteriors"]),
                "citizen_level1": _sanitize_json(payload["citizen_level1"]),
                "researcher_level2": _sanitize_json(payload["researcher_level2"]),
                "model_version": version,
                "created_at": _now(),
            }
            self.model2_classifications[key] = row
            return copy.deepcopy(row)

    def get_model2_classification(
        self, patch_id: int, model_version: str = "v1"
    ) -> dict[str, Any] | None:
        row = self.model2_classifications.get((patch_id, model_version))
        return copy.deepcopy(row) if row else None

    def save_model3_forecast(self, patch_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        version = payload.get("model_version", "v1")
        with self._lock:
            key = (patch_id, version)
            existing = self.model3_forecasts.get(key)
            row_id = existing["id"] if existing else self._next("m3")
            row = {
                "id": row_id,
                "patch_id": patch_id,
                "model1_attribution_id": payload.get("model1_attribution_id"),
                "gp_hyperparams": _sanitize_json(payload["gp_hyperparams"]),
                "forecast_series": _sanitize_json(payload["forecast_series"]),
                "predicted_cone": _sanitize_json(payload["predicted_cone"]),
                "z_alert": _clean_float(payload.get("z_alert")),
                "mahalanobis_d2": _clean_float(payload.get("mahalanobis_d2")),
                "delta_log_likelihood": _clean_float(payload.get("delta_log_likelihood")),
                "alert_triggered": bool(payload.get("alert_triggered", False)),
                "citizen_level1": _sanitize_json(payload["citizen_level1"]),
                "researcher_level2": _sanitize_json(payload["researcher_level2"]),
                "model_version": version,
                "created_at": _now(),
            }
            self.model3_forecasts[key] = row
            return copy.deepcopy(row)

    def get_model3_forecast(
        self, patch_id: int, model_version: str = "v1"
    ) -> dict[str, Any] | None:
        row = self.model3_forecasts.get((patch_id, model_version))
        return copy.deepcopy(row) if row else None

    def save_citizen_vote(
        self,
        patch_id: int,
        epoch_index: int,
        vote: str,
        *,
        voter_token: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            row = {
                "id": self._next("vote"),
                "patch_id": patch_id,
                "epoch_index": int(epoch_index),
                "vote": vote,
                "voter_token": voter_token,
                "comment": comment,
                "created_at": _now(),
            }
            self.citizen_votes.append(row)
            return copy.deepcopy(row)

    def list_citizen_votes(
        self, patch_id: int, epoch_index: int | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            copy.deepcopy(v)
            for v in self.citizen_votes
            if v["patch_id"] == patch_id and (epoch_index is None or v["epoch_index"] == epoch_index)
        ]
        return sorted(rows, key=lambda x: x["id"])
