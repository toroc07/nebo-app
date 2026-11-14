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
};
export type Timeline = {
  status: "ready";
  patch: { ra: number; dec: number };
  detector: { id: number; wavelength_range_um: number[] };
  size: { side_arcmin: number; pixel_scale_arcsec: number };
  epochs: Epoch[];
};
export type Building = {
  status: "building";
  progress: { stage: string; done: number; total: number };
  retry_after_s: number;
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
          ? "We could not prepare this field. Try another detector or try again in a minute."
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
export function nextEpoch(index: number, count: number) {
  return count > 1 ? (index + 1) % count : 0;
}
