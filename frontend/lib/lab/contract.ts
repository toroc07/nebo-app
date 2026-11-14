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
  /** Which image set these epochs come from. Added by `loadTimeline`; not part of the API body. */
  palette: Palette;
};

export type LabTarget = {
  slug: string;
  name: string;
  kind: string;
  note: string;
  recommended_detector: number;
};

export type Source = "demo" | "api";

/**
 * How an epoch image is painted. "gray" is the raw infrared band (brightness only); "amber" and
 * "inferno" are display palettes applied to that same single band, not the sky's real colours.
 * Only the demo export has palettes: the real API returns grey images.
 */
export type Palette = "gray" | "amber" | "inferno";
export type ColorPalette = Exclude<Palette, "gray">;

export const colorPalettes: { id: ColorPalette; label: string }[] = [
  { id: "inferno", label: "Inferno" },
  { id: "amber", label: "Amber" },
];

/** URL prefix of each demo image set; mirrors the folder map in app/lab/demo/[...path]/route.ts. */
export function demoBase(palette: Palette = "gray"): string {
  return palette === "gray" ? "/lab/demo/" : `/lab/demo/${palette}/`;
}

export async function loadTargets(source: Source): Promise<LabTarget[]> {
  const r = await fetch(
    source === "demo"
      ? demoBase() + "targets.json"
      : imageUrl("/api/v1/targets"),
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
  palette: Palette = "gray",
): Promise<LabTimeline> {
  if (source === "demo") {
    const r = await fetch(
      `${demoBase(palette)}timeline/${slug}_d${detector}_${size}.json`,
      { signal },
    );
    if (!r.ok)
      throw new Error(
        `No ${palette} demo timeline for ${slug} D${detector} ${size}`,
      );
    return { ...(await r.json()), palette };
  }
  const query: Query = { target: slug };
  const data = await fetchTimeline(query, size, detector, signal, (b) =>
    onBuilding?.(b.progress.stage, b.progress.done, b.progress.total),
  );
  // The API returns more fields than lib/api.ts types; here we use them as they come.
  return { ...(data as unknown as LabTimeline), palette: "gray" };
}

/** Image URL of an epoch. `image_url` is relative to the folder of the timeline it came from. */
export function epochImageUrl(
  source: Source,
  epoch: LabEpoch,
  palette: Palette,
): string {
  return source === "demo"
    ? demoBase(palette) + epoch.image_url
    : imageUrl(epoch.image_url);
}
