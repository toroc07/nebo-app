// Observation lab. FULL contract of `GET /timeline` (backend/app/main.py and shared/demo), a
// superset of the `Timeline` in lib/api.ts, which today omits sector, data, releases and
// expected_position. It imports from lib/api.ts but does not modify it.
import { imageUrl, timeline as fetchTimeline, type Query } from "@/lib/api";

export type ExpectedPosition = {
  ra: number;
  dec: number;
  // Pixel inside the image (0,0 = top-left corner, north up, east to the left).
  x: number;
  y: number;
  in_image: boolean;
};

export type LabEpoch = {
  index: number;
  start_utc: string;
  end_utc: string;
  mid_mjd: number;
  frames_available: number;
  frames_used: number;
  // Brightness scale shared by all epochs of one size.
  display_min: number;
  display_max: number;
  releases: string[];
  expected_position?: ExpectedPosition;
  image_url: string;
};

export type LabTimeline = {
  status: "ready";
  patch: { id: number; ra: number; dec: number; target: string | null };
  detector: { id: number; bandpass: string; wavelength_range_um: number[] };
  size: {
    name: string;
    side_deg: number;
    side_arcmin: number;
    width_px: number;
    height_px: number;
    pixel_scale_arcsec: number;
  };
  orientation: string;
  sector?: {
    center: { ra: number; dec: number };
    corners: Record<"NW" | "NE" | "SE" | "SW", [number, number]>;
  };
  data?: { source: string; processed_at: string };
  display: { stretch: string; unit: string; note: string };
  epochs: LabEpoch[];
  frames_found: number;
  frames_used: number;
  updated_at: string;
};

export type LabTarget = {
  slug: string;
  name: string;
  kind: string;
  note: string;
  recommended_detector: number;
};

export type Source = "demo" | "api";

export const demoBase = "/lab/demo/";

export async function loadTargets(source: Source): Promise<LabTarget[]> {
  const r = await fetch(
    source === "demo" ? demoBase + "targets.json" : imageUrl("/api/v1/targets"),
  );
  if (!r.ok) throw new Error(`targets: HTTP ${r.status}`);
  return r.json();
}

// Single entry point for demo and API: the rest of the viewer does not know where data comes from.
export async function loadTimeline(
  source: Source,
  slug: string,
  detector: number,
  size: string,
  signal: AbortSignal,
  onBuilding?: (stage: string, done: number, total: number) => void,
): Promise<LabTimeline> {
  if (source === "demo") {
    const r = await fetch(
      `${demoBase}timeline/${slug}_d${detector}_${size}.json`,
      {
        signal,
      },
    );
    if (!r.ok)
      throw new Error(`No demo timeline for ${slug} D${detector} ${size}`);
    return r.json();
  }
  const query: Query = { target: slug };
  const data = await fetchTimeline(query, size, detector, signal, (b) =>
    onBuilding?.(b.progress.stage, b.progress.done, b.progress.total),
  );
  // The API returns more fields than lib/api.ts types; here we use them as they come.
  return data as unknown as LabTimeline;
}

export function epochImageUrl(source: Source, epoch: LabEpoch): string {
  return source === "demo"
    ? demoBase + epoch.image_url
    : imageUrl(epoch.image_url);
}
