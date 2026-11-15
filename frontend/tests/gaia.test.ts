import { test } from "node:test";
import assert from "node:assert/strict";
import {
  FAST_MOVER_MAS_YR,
  gaiaMarks,
  gaiaSummary,
  type GaiaField,
  type GaiaStar,
} from "../lib/lab/gaia";

// World = the large image (147 px); medium (59 px) is its central crop, offset by 44 px.
const WORLD = { width: 147, height: 147 };
const MEDIUM = { width: 59, height: 59 };

function star(id: string, xy: [number, number][], pm: number | null = 5): GaiaStar {
  return {
    source_id: id,
    g_mag: 12,
    bp_rp: 1,
    pm_ra_mas_yr: pm,
    pm_dec_mas_yr: 0,
    pm_total_mas_yr: pm,
    parallax_mas: 1,
    distance_pc: 1000,
    positions: xy.map(([x, y], i) => ({
      mjd: 61000 + i * 180,
      ra: 0,
      dec: 0,
      x,
      y,
      in_image: true,
    })),
  };
}

function field(stars: GaiaStar[], truncated = false): GaiaField {
  return {
    patch_id: 1,
    size: { name: "large", width_px: 147, height_px: 147 },
    catalog: {
      name: "Gaia DR3",
      ref_epoch: 2016,
      g_max: 18,
      g_complete: truncated ? 16.4 : 18,
      radius_deg: 0.227,
      truncated,
      note: "",
    },
    mjd: [61000, 61180],
    stars,
  };
}

test("every star of the world is drawn at the largest level", () => {
  const f = field([star("a", [[0, 0], [0, 0]]), star("b", [[146, 146], [146, 146]])]);
  assert.deepEqual(
    gaiaMarks(f, 0, WORLD, WORLD).map((m) => m.id),
    ["a", "b"],
  );
});

test("a smaller level only draws the stars inside its central crop", () => {
  const f = field([
    star("centre", [[73, 73], [73, 73]]),
    star("corner", [[2, 2], [2, 2]]),
    star("edge-in", [[44, 102], [44, 102]]), // first and last pixel of the crop
    star("edge-out", [[43, 73], [43, 73]]),
  ]);
  assert.deepEqual(
    gaiaMarks(f, 0, WORLD, MEDIUM).map((m) => m.id),
    ["centre", "edge-in"],
  );
});

test("marks follow the epoch, so a mover can leave the crop", () => {
  const f = field([star("mover", [[73, 45], [73, 40]], 10_000)]);
  const first = gaiaMarks(f, 0, WORLD, MEDIUM);
  assert.equal(first.length, 1);
  assert.equal(first[0].y, 45);
  assert.equal(first[0].fast, true);
  assert.deepEqual(gaiaMarks(f, 1, WORLD, MEDIUM), []);
  assert.deepEqual(gaiaMarks(f, 5, WORLD, MEDIUM), []); // no such epoch
});

test("fast movers are flagged by proper motion; unknown motion is not fast", () => {
  const f = field([
    star("slow", [[73, 73]], FAST_MOVER_MAS_YR - 1),
    star("fast", [[74, 73]], FAST_MOVER_MAS_YR),
    star("unknown", [[75, 73]], null),
  ]);
  assert.deepEqual(
    gaiaMarks(f, 0, WORLD, WORLD).map((m) => [m.id, m.fast]),
    [
      ["slow", false],
      ["fast", true],
      ["unknown", false],
    ],
  );
});

test("the summary always names the completeness limit", () => {
  const f = field([star("a", [[73, 73]], 10_000), star("b", [[70, 70]])]);
  assert.equal(
    gaiaSummary(f, gaiaMarks(f, 0, WORLD, WORLD)),
    "2 stars on this image · 1 fast mover · complete to G 18.0",
  );
  const dense = field([star("a", [[73, 73]])], true);
  assert.equal(
    gaiaSummary(dense, gaiaMarks(dense, 0, WORLD, WORLD)),
    "1 star on this image · complete to G 16.4 (dense field, fainter stars omitted)",
  );
});
