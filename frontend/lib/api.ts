export type Target = {
  slug: string;
  name: string;
  ra: number;
  dec: number;
  kind: string;
  note: string;
  recommended_detector: number;
};
export type Patch = {
  id: number;
  target_slug: string | null;
  detectors_ready: number[];
  ra: number;
  dec: number;
};
export type Query =
  | { target: string; ra?: never; dec?: never }
  | { target?: never; ra: number; dec: number };
export type Epoch = {
  index: number;
  start_utc: string;
  end_utc: string;
  image_url: string;
  frames_used: number;
  // SPHEREx data releases of the exposures in this epoch, e.g. ["dr1"] or ["dr1", "qr3"].
  releases?: string[];
};
export type Timeline = {
  status: "ready";
  patch: { id: number; ra: number; dec: number; target?: string | null };
  detector: { id: number; bandpass?: string; wavelength_range_um: number[] };
  size: { name?: string; side_arcmin: number; width_px?: number; height_px?: number; pixel_scale_arcsec: number };
  epochs: Epoch[];
};

export type SpectralChannelPoint = {
  channel_id: number;
  band: number;
  lambda_c_um: number;
  flux_mjy: number | null;
  sigma_mjy: number | null;
  is_blankch?: boolean;
};

export type SpectralIndexValue = {
  index_code: string;
  value: number | null;
  uncertainty: number | null;
  snr?: number | null;
  is_significant_3s?: boolean;
  is_valid?: boolean;
};

export type PatchSpectrumResponse = {
  patch_id: number;
  epoch_index: number;
  simulated?: boolean;
  data_note?: string;
  channels: SpectralChannelPoint[];
  indices?: SpectralIndexValue[];
};

export type ImagePhotometryPoint = {
  epoch_index: number;
  mid_mjd: number;
  // null when the epoch has no usable pixels or variance.
  flux_hat: number | null;
  sigma_stat: number | null;
  sigma_reported: number | null;
  snr: number | null;
  q_fit_epsf: number;
  chi2_psf: number;
  p_clean_flags: number;
  f_artifact_flags: number;
};

export type PatchMetricsResponse = {
  patch: { id: number; ra: number; dec: number; target?: string | null };
  simulated?: boolean;
  data_note?: string;
  // Names as the backend sends them (metrics.compute_global_confidence_score and friends).
  confidence: {
    c_global: number;
    s_snr?: number;
    s_dipole?: number;
    s_flags?: number;
    s_psf?: number;
  };
  variability: {
    n_epochs?: number;
    weighted_mean_mjy?: number;
    chi2_var_reduced?: number;
    stetson_j?: number;
    von_neumann_eta?: number;
    lomb_scargle_power?: number;
    lomb_scargle_period_days?: number | null;
    is_variable?: boolean;
  };
  spectral_indices: SpectralIndexValue[];
  image_photometry: ImagePhotometryPoint[];
};

export type Model1EventResponse = {
  predicted_class: string;
  probabilities: Record<string, number>;
  temperature_t?: number;
  treeshap_values?: {
    base_value?: number;
    per_feature?: Record<string, number>;
    top_drivers?: Array<{
      feature: string;
      phi: number;
    }>;
  };
  citizen_level1?: {
    traffic_light?: string;
    headline?: string;
    confidence_score_pct?: number;
    badge?: string;
    explanation?: string;
  };
  simulated?: boolean;
  data_note?: string;
};

export type Model2SpectrumResponse = {
  predicted_class: string;
  best_template_name: string;
  chi2_reduced: number;
  bayesian_posteriors: Record<string, number>;
  citizen_level1?: {
    probable_identity: string;
    confidence_pct: number;
    chemical_fingerprints: string[];
    fit_quality: string;
  };
  simulated?: boolean;
  data_note?: string;
};

export type Model3ForecastResponse = {
  forecast_series?: Array<{
    mjd: number;
    flux_mean_mjy: number;
    flux_std_mjy: number;
  }>;
  predicted_cone?: {
    target_mjd: number;
    horizon_days: number;
    ra_pred_deg: number;
    dec_pred_deg: number;
    cone_radius_1s_arcsec: number;
    cone_radius_3s_arcsec: number;
  };
  z_alert?: number;
  mahalanobis_d2?: number;
  alert_triggered?: boolean;
  citizen_level1?: {
    alert_status?: string;
    alert_triggered?: boolean;
    vetoed_by_model1?: boolean;
    summary?: string;
  };
  simulated?: boolean;
  data_note?: string;
};

export type CandidateDetection = {
  x: number;
  y: number;
  ra: number;
  dec: number;
  snr: number;
  delta_flux: number;
  label: "catalogued_object" | "candidate_signal";
  gaia_match?: { source_id: string; g_mag: number; dist_arcsec: number } | null;
  wise_match?: { source_id: string; w1_mag: number; w2_mag: number; dist_arcsec: number } | null;
};

export type CandidatesResponse = {
  patch_id: number;
  detector: number;
  size: string;
  epoch_a: number;
  epoch_b: number;
  gaia_available: boolean;
  wise_available: boolean;
  gaia_complete_to_g: number | null;
  candidates: CandidateDetection[];
};

export type CitizenVote = {
  id: number;
  patch_id: number;
  epoch_index: number;
  vote: string;
  comment?: string | null;
  created_at: string;
};
export type Building = {
  status: "building";
  progress: { stage: string; done: number; total: number };
  retry_after_s: number;
  // Progressive builds already carry the epochs rendered so far (fewer frames per epoch).
  epochs?: Epoch[];
};
export const origin = (
  process.env.NEXT_PUBLIC_API_ORIGIN || "http://127.0.0.1:8000"
).replace(/\/$/, "");
export class ApiError extends Error {
  constructor(
    public status: number,
    public code?: string,
    public retryAfter = 0,
  ) {
    super(
      status === 503
        ? code === "database_not_configured"
          ? "The database is not configured yet. Connect PostgreSQL to query the images."
          : "The service is unavailable. Try again in a few moments."
        : status === 502
          ? code === "archive_unavailable"
            ? "NASA's IRSA archive is not responding right now. This is on their side, not your field: try again in a few minutes."
            : "We could not prepare this field. Try another detector or try again in a minute."
          : status === 404
            ? "We could not find this object. Go back to the catalog."
            : status === 422
              ? "Check the coordinates and try again."
              : "We could not reach the image service. Check your connection and try again.",
    );
  }
}
export async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  let r: Response;
  try {
    r = await fetch(origin + "/api/v1" + path, { signal });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError(0);
  }
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new ApiError(
      r.status,
      b.code,
      Number(r.headers.get("Retry-After")) || 0,
    );
  }
  return r.json();
}
export async function post<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let r: Response;
  try {
    r = await fetch(origin + "/api/v1" + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (signal?.aborted) throw e;
    throw new ApiError(0);
  }
  if (!r.ok) {
    const b = await r.json().catch(() => ({}));
    throw new ApiError(
      r.status,
      b.code,
      Number(r.headers.get("Retry-After")) || 0,
    );
  }
  return r.json();
}
export function validCoordinates(ra: string, dec: string) {
  return (
    ra.trim() !== "" &&
    dec.trim() !== "" &&
    Number.isFinite(Number(ra)) &&
    Number.isFinite(Number(dec)) &&
    Number(ra) >= 0 &&
    Number(ra) < 360 &&
    Number(dec) >= -90 &&
    Number(dec) <= 90
  );
}
export async function timeline(
  query: Query,
  size: string,
  detector: number,
  signal: AbortSignal,
  onProgress: (p: Building) => void,
): Promise<Timeline> {
  const p = new URLSearchParams({
    ...Object.fromEntries(
      Object.entries(query).map(([k, v]) => [k, String(v)]),
    ),
    size,
    detector: String(detector),
  });
  while (!signal.aborted) {
    const r = await fetch(origin + "/api/v1/timeline?" + p, { signal }).catch(
      (e) => {
        if (signal.aborted) throw e;
        throw new ApiError(0);
      },
    );
    const b = await r.json();
    if (!r.ok)
      throw new ApiError(
        r.status,
        b.code,
        Number(r.headers.get("Retry-After")) || 0,
      );
    if (r.status !== 202) return b as Timeline;
    onProgress(b);
    await new Promise<void>((resolve, reject) => {
      const abort = () => {
        clearTimeout(id);
        reject(new DOMException("Aborted", "AbortError"));
      };
      const id = setTimeout(
        () => {
          signal.removeEventListener("abort", abort);
          resolve();
        },
        Math.max(
          1,
          Number(r.headers.get("Retry-After")) || b.retry_after_s || 5,
        ) * 1000,
      );
      signal.addEventListener("abort", abort, { once: true });
    });
  }
  throw new DOMException("Aborted", "AbortError");
}
export function imageUrl(path: string) {
  return new URL(path, origin).href;
}
// An epoch groups exposures taken over days or weeks, so show its whole span (UTC):
// "Aug 15, 2025", "Mar 19 – May 5, 2026" or "Dec 28, 2025 – Jan 3, 2026".
export function epochDateRange(startUtc: string, endUtc?: string) {
  const start = new Date(startUtc);
  if (Number.isNaN(start.getTime())) return "";
  const end = endUtc ? new Date(endUtc) : start;
  const format = (d: Date, withYear: boolean) =>
    d.toLocaleDateString("en", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
      ...(withYear ? { year: "numeric" } : {}),
    });
  const day = (d: Date) => d.toISOString().slice(0, 10);
  if (Number.isNaN(end.getTime()) || day(start) === day(end))
    return format(start, true);
  const sameYear = start.getUTCFullYear() === end.getUTCFullYear();
  return `${format(start, !sameYear)} – ${format(end, true)}`;
}
// "SPHEREx DR1 + QR3" for an epoch, from the releases the API reports (never hard-coded).
export function releaseLabel(releases?: string[]) {
  const names = [
    ...new Set((releases ?? []).map((r) => r.trim().toUpperCase())),
  ]
    .filter(Boolean)
    .sort();
  return names.length ? `SPHEREx ${names.join(" + ")}` : "SPHEREx";
}
export function nextEpoch(index: number, count: number) {
  return count > 1 ? (index + 1) % count : 0;
}

function queryParams(query: Query, extra: Record<string, string | number>) {
  const base = Object.fromEntries(
    Object.entries(query).map(([k, v]) => [k, String(v)]),
  );
  return new URLSearchParams({
    ...base,
    ...Object.fromEntries(
      Object.entries(extra).map(([k, v]) => [k, String(v)]),
    ),
  });
}

export function diffImageUrl(
  query: Query,
  opts: { a: number; b: number; detector: number; size: string },
) {
  return `${origin}/api/v1/timeline/diff?${queryParams(query, opts)}`;
}

export function rgbImageUrl(
  query: Query,
  opts: { r: number; g: number; b: number; epoch: number; size: string },
) {
  return `${origin}/api/v1/timeline/rgb?${queryParams(query, opts)}`;
}

export function fetchPatchSpectrum(
  patchId: number,
  epochIndex = -1,
  signal?: AbortSignal,
) {
  return read<PatchSpectrumResponse>(
    `/patches/${patchId}/spectrum?epoch_index=${epochIndex}`,
    signal,
  );
}

export function fetchPatchMetrics(
  patchId: number,
  detector?: number,
  signal?: AbortSignal,
) {
  const qs = detector ? `?detector=${detector}` : "";
  return read<PatchMetricsResponse>(`/patches/${patchId}/metrics${qs}`, signal);
}

export function fetchPatchCandidates(
  patchId: number,
  opts: {
    detector: number;
    size: string;
    epoch_a: number;
    epoch_b: number;
    snr_threshold?: number;
  },
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams(
    Object.entries(opts).map(([k, v]) => [k, String(v)]),
  );
  return read<CandidatesResponse>(
    `/patches/${patchId}/candidates?${qs}`,
    signal,
  );
}

export function fetchModel1Event(patchId: number, signal?: AbortSignal) {
  return read<Model1EventResponse>(
    `/patches/${patchId}/models/event`,
    signal,
  );
}

export function fetchModel2Spectrum(patchId: number, signal?: AbortSignal) {
  return read<Model2SpectrumResponse>(
    `/patches/${patchId}/models/spectrum`,
    signal,
  );
}

export function fetchModel3Forecast(patchId: number, signal?: AbortSignal) {
  return read<Model3ForecastResponse>(
    `/patches/${patchId}/models/forecast`,
    signal,
  );
}

export function fetchCitizenVotes(patchId: number, signal?: AbortSignal) {
  return read<CitizenVote[]>(`/patches/${patchId}/votes`, signal);
}

export function submitCitizenVote(
  patchId: number,
  payload: { epoch_index: number; vote: string; comment?: string },
  signal?: AbortSignal,
) {
  return post<CitizenVote>(`/patches/${patchId}/votes`, payload, signal);
}
