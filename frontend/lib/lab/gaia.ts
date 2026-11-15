// Gaia DR3 overlay of the observation lab: catalogued stars drawn on the SPHEREx image, moved to
// the date of the epoch on screen (contract: `GET /patches/{id}/gaia` in backend/README.md).
//
// The stars are requested once per observation, at the size of the viewer's world (the largest
// loaded level), with the mid date of every epoch. Each level is a central crop of the world,
// so the same answer serves every zoom level: only the stars inside the level on screen are drawn.
// Relative import (not "@/lib/api") so the node test runner can load this file directly.
import { read } from "../api";
import { levelOffset } from "./fov";
import type { Size } from "./viewport";

export type GaiaPosition = {
  mjd: number;
  ra: number;
  dec: number;
  // 0-based pixel index in the requested size's image (north up, east left).
  x: number;
  y: number;
  in_image: boolean;
};

export type GaiaStar = {
  source_id: string;
  g_mag: number | null;
  bp_rp: number | null;
  pm_ra_mas_yr: number | null;
  pm_dec_mas_yr: number | null;
  pm_total_mas_yr: number | null;
  parallax_mas: number | null;
  distance_pc: number | null;
  /** One per requested date, in the same order as `GaiaField.mjd`. */
  positions: GaiaPosition[];
};

export type GaiaField = {
  patch_id: number;
  size: { name: string; width_px: number; height_px: number };
  catalog: {
    name: string;
    ref_epoch: number;
    g_max: number;
    /** The list holds every Gaia star down to this G magnitude (lower than g_max when truncated). */
    g_complete: number;
    radius_deg: number;
    truncated: boolean;
    note: string;
  };
  mjd: number[];
  stars: GaiaStar[];
};

/**
 * Stars at or above this proper motion are drawn as "fast movers". 100 mas/yr singles out nearby
 * stars (Barnard's Star moves ~10 400 mas/yr); background stars move a few mas/yr.
 */
export const FAST_MOVER_MAS_YR = 100;

export async function loadGaia(
  patchId: number,
  size: string,
  mjds: number[],
  signal?: AbortSignal,
): Promise<GaiaField> {
  const q = new URLSearchParams({ size });
  for (const m of mjds) q.append("mjd", String(m));
  return read<GaiaField>(`/patches/${patchId}/gaia?${q}`, signal);
}

/** A star ready to draw: world pixel index of its centre at the chosen epoch. */
export type GaiaMark = {
  id: string;
  x: number;
  y: number;
  fast: boolean;
};

/**
 * Stars inside the level on screen at epoch `index`. `field` must have been requested at the
 * world's size; `level` is the size of the image being shown, centred in the world.
 */
export function gaiaMarks(
  field: GaiaField,
  index: number,
  world: Size,
  level: Size,
): GaiaMark[] {
  const o = levelOffset(world, level);
  const marks: GaiaMark[] = [];
  for (const star of field.stars) {
    const p = star.positions[index];
    if (!p) continue;
    // Pixel i covers [i - 0.5, i + 0.5] around its centre.
    if (
      p.x < o.x - 0.5 ||
      p.y < o.y - 0.5 ||
      p.x > o.x + level.width - 0.5 ||
      p.y > o.y + level.height - 0.5
    )
      continue;
    marks.push({
      id: star.source_id,
      x: p.x,
      y: p.y,
      fast: (star.pm_total_mas_yr ?? 0) >= FAST_MOVER_MAS_YR,
    });
  }
  return marks;
}

/**
 * One line for the details panel. It names the completeness limit, so an empty spot on the image
 * reads "no Gaia star brighter than G = …", never "uncatalogued" on its own.
 */
export function gaiaSummary(field: GaiaField, shown: GaiaMark[]): string {
  const fast = shown.filter((m) => m.fast).length;
  const limit = field.catalog.g_complete.toFixed(1);
  return (
    `${shown.length} ${shown.length === 1 ? "star" : "stars"} on this image` +
    (fast ? ` · ${fast} fast ${fast === 1 ? "mover" : "movers"}` : "") +
    ` · complete to G ${limit}` +
    (field.catalog.truncated ? " (dense field, fainter stars omitted)" : "")
  );
}
