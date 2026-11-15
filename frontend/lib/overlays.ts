// Catalog layers of the field viewer: CatWISE2020 sources, Gaia trajectories, the alignment check
// and suggested destinations (contracts: `/patches/{id}/wise`, `/patches/{id}/alignment` and
// `/explore/suggested` in backend/README.md). Gaia stars come from lib/lab/gaia.ts.
// Relative imports so the node test runner can load this file directly.
import { read, type CandidateDetection } from "./api";
import {
  FAST_MOVER_MAS_YR,
  type GaiaPosition,
  type GaiaStar,
} from "./lab/gaia";

export type WiseSource = {
  source_id: string;
  w1_mag: number | null;
  w2_mag: number | null;
  w1_w2_color: number | null;
  pm_ra_mas_yr: number | null;
  pm_dec_mas_yr: number | null;
  pm_total_mas_yr: number | null;
  gaia_match: {
    source_id: string;
    dist_arcsec: number;
    g_mag: number | null;
  } | null;
  /** Red in W1−W2 and with no Gaia counterpart: an infrared source Gaia cannot see. */
  cold_candidate: boolean;
  /** One per requested date, in the same order as the request's `mjd`. */
  positions: GaiaPosition[];
};

export type WiseField = {
  patch_id: number;
  size: { name: string; width_px: number; height_px: number };
  catalog: {
    name: string;
    w2_max: number;
    w2_complete: number;
    truncated: boolean;
  };
  sources: WiseSource[];
};

export type AlignmentEpoch = {
  epoch_index: number;
  mid_mjd: number;
  stars_used: number;
  median_dx_px: number | null;
  median_dy_px: number | null;
  rms_arcsec: number | null;
  status: "ok" | "offset_warning" | "insufficient_stars";
  /** Set only on the made-up row of the "Simulate offset" demo. */
  simulated?: boolean;
};

export type Alignment = {
  patch_id: number;
  detector: number;
  size: string;
  epochs: AlignmentEpoch[];
};

export type Destination = {
  source_id: string;
  name: string;
  ra: number;
  dec: number;
  pm_total_mas_yr: number | null;
  distance_pc: number | null;
  g_mag: number | null;
  bp_rp: number | null;
};

export type Suggestions = { source: string; destinations: Destination[] };

function mjdQuery(size: string, mjds: number[]) {
  const q = new URLSearchParams({ size });
  for (const m of mjds) q.append("mjd", String(m));
  return q;
}

export function loadWise(
  patchId: number,
  size: string,
  mjds: number[],
  signal?: AbortSignal,
) {
  return read<WiseField>(
    `/patches/${patchId}/wise?${mjdQuery(size, mjds)}`,
    signal,
  );
}

export function loadAlignment(
  patchId: number,
  detector: number,
  size: string,
  signal?: AbortSignal,
) {
  return read<Alignment>(
    `/patches/${patchId}/alignment?detector=${detector}&size=${size}`,
    signal,
  );
}

export function loadSuggestions(ra: number, dec: number, signal?: AbortSignal) {
  return read<Suggestions>(
    `/explore/suggested?ra=${ra}&dec=${dec}&limit=8`,
    signal,
  );
}

/** A CatWISE source ready to draw at epoch `index` (pixel indices of the image on screen). */
export type WiseMark = { id: string; x: number; y: number; cold: boolean };

export function wiseMarks(field: WiseField, index: number): WiseMark[] {
  const marks: WiseMark[] = [];
  for (const s of field.sources) {
    const p = s.positions[index];
    if (p?.in_image)
      marks.push({ id: s.source_id, x: p.x, y: p.y, cold: s.cold_candidate });
  }
  return marks;
}

/** First-to-last epoch path of a fast Gaia star, or null for slow stars and single epochs. */
export function trajectory(
  star: GaiaStar,
): { from: GaiaPosition; to: GaiaPosition } | null {
  const from = star.positions[0],
    to = star.positions[star.positions.length - 1];
  if (
    (star.pm_total_mas_yr ?? 0) < FAST_MOVER_MAS_YR ||
    !from ||
    !to ||
    from === to
  )
    return null;
  return { from, to };
}

export const LY_PER_PC = 3.26156;

/** What the user clicked on the image. */
export type Selection =
  | { kind: "gaia"; star: GaiaStar }
  | { kind: "wise"; source: WiseSource }
  | { kind: "change"; change: CandidateDetection };

const num = (v: number | null | undefined, digits: number, unit = "") =>
  v == null ? "—" : `${v.toFixed(digits)}${unit}`;

/** Rows of the detail card, as [label, value]. */
export function detailFor(sel: Selection): {
  title: string;
  rows: [string, string][];
} {
  if (sel.kind === "gaia") {
    const s = sel.star,
      d = s.distance_pc;
    return {
      title: `Gaia DR3 ${s.source_id}`,
      rows: [
        [
          "Distance",
          d == null
            ? "— (no parallax)"
            : `${d.toFixed(2)} pc · ${(d * LY_PER_PC).toFixed(2)} ly`,
        ],
        ["Brightness", num(s.g_mag, 2, " G")],
        ["Proper motion", num(s.pm_total_mas_yr, 1, " mas/yr")],
        ["Colour", num(s.bp_rp, 2, " BP−RP")],
        [
          "Status",
          (s.pm_total_mas_yr ?? 0) >= FAST_MOVER_MAS_YR
            ? "Catalogued object · fast mover"
            : "Catalogued object",
        ],
      ],
    };
  }
  if (sel.kind === "wise") {
    const s = sel.source;
    return {
      title: `CatWISE2020 ${s.source_id}`,
      rows: [
        ["Distance", "— (CatWISE has no parallax)"],
        [
          "Brightness",
          `${num(s.w1_mag, 2, " W1")} · ${num(s.w2_mag, 2, " W2")}`,
        ],
        ["Proper motion", num(s.pm_total_mas_yr, 1, " mas/yr")],
        ["Colour", num(s.w1_w2_color, 2, " W1−W2")],
        [
          "Status",
          s.cold_candidate
            ? "Cold candidate · no Gaia counterpart"
            : s.gaia_match
              ? `Catalogued · Gaia match at ${s.gaia_match.dist_arcsec.toFixed(1)}″`
              : "Infrared source · no Gaia counterpart",
        ],
      ],
    };
  }
  const c = sel.change;
  return {
    title: "Observed change",
    rows: [
      ["Position", `RA ${c.ra.toFixed(4)}° · Dec ${c.dec.toFixed(4)}°`],
      [
        "Brightness",
        c.gaia_match
          ? `${c.gaia_match.g_mag.toFixed(2)} G`
          : c.wise_match
            ? `${c.wise_match.w2_mag.toFixed(2)} W2`
            : "—",
      ],
      ["Signal", `SNR ${c.snr.toFixed(1)} · Δflux ${c.delta_flux.toFixed(2)}`],
      ["Status", changeLabel(c)],
    ],
  };
}

/** Known vs new: the badge text of a detected change. Never claims a discovery. */
export function changeLabel(c: CandidateDetection): string {
  if (c.label === "catalogued_object") return "Catalogued object";
  return c.gaia_match ? "Candidate signal" : "Cold candidate (no Gaia)";
}

/** Demo shift of the "Simulate offset" control, in image pixels (2 px ≈ 12″). */
export const SIMULATED_OFFSET_PX = { dx: 2, dy: -1 };

/** The alignment row to show for `epoch`: the real one, or a made-up offset when simulating. */
export function alignmentFor(
  alignment: Alignment | null,
  epoch: number,
  simulate: boolean,
): AlignmentEpoch | null {
  const real = alignment?.epochs.find((e) => e.epoch_index === epoch) ?? null;
  if (!simulate) return real;
  const { dx, dy } = SIMULATED_OFFSET_PX;
  return {
    epoch_index: epoch,
    mid_mjd: real?.mid_mjd ?? 0,
    stars_used: real?.stars_used ?? 0,
    median_dx_px: dx,
    median_dy_px: dy,
    rms_arcsec: Math.hypot(dx, dy) * 6.15,
    status: "offset_warning",
    simulated: true,
  };
}
