import { test } from "node:test";
import assert from "node:assert/strict";
import type { CandidateDetection } from "../lib/api";
import type { GaiaStar } from "../lib/lab/gaia";
import {
  alignmentFor,
  changeLabel,
  detailFor,
  trajectory,
  wiseMarks,
  type Alignment,
  type WiseField,
  type WiseSource,
} from "../lib/overlays";

const pos = (x: number, y: number, in_image = true) => ({
  mjd: 0,
  ra: 0,
  dec: 0,
  x,
  y,
  in_image,
});

function gaiaStar(pm: number | null, distance: number | null = 1.83): GaiaStar {
  return {
    source_id: "4472832130114786688",
    g_mag: 8.19,
    bp_rp: 2.83,
    pm_ra_mas_yr: null,
    pm_dec_mas_yr: null,
    pm_total_mas_yr: pm,
    parallax_mas: null,
    distance_pc: distance,
    positions: [pos(29, 29), pos(30, 27)],
  };
}

function wiseSource(
  id: string,
  positions: ReturnType<typeof pos>[],
  cold = false,
): WiseSource {
  return {
    source_id: id,
    w1_mag: 17.3,
    w2_mag: 13.9,
    w1_w2_color: 3.4,
    pm_ra_mas_yr: null,
    pm_dec_mas_yr: null,
    pm_total_mas_yr: 8100,
    gaia_match: null,
    cold_candidate: cold,
    positions,
  };
}

test("wiseMarks keeps sources inside the image at the chosen epoch", () => {
  const field = {
    sources: [
      wiseSource("a", [pos(1, 2), pos(3, 4, false)], true),
      wiseSource("b", [pos(5, 6, false), pos(7, 8)]),
    ],
  } as WiseField;
  assert.deepEqual(wiseMarks(field, 0), [{ id: "a", x: 1, y: 2, cold: true }]);
  assert.deepEqual(wiseMarks(field, 1), [{ id: "b", x: 7, y: 8, cold: false }]);
});

test("trajectory is drawn only for fast movers", () => {
  assert.deepEqual(trajectory(gaiaStar(10393)), {
    from: pos(29, 29),
    to: pos(30, 27),
  });
  assert.equal(trajectory(gaiaStar(5)), null);
  assert.equal(trajectory(gaiaStar(null)), null);
  assert.equal(
    trajectory({ ...gaiaStar(10393), positions: [pos(1, 1)] }),
    null,
  );
});

test("detailFor converts parsecs to light-years and handles missing parallax", () => {
  const rows = Object.fromEntries(
    detailFor({ kind: "gaia", star: gaiaStar(10393.4) }).rows,
  );
  assert.equal(rows.Distance, "1.83 pc · 5.97 ly");
  assert.equal(rows["Proper motion"], "10393.4 mas/yr");
  assert.equal(rows.Colour, "2.83 BP−RP");
  assert.match(rows.Status, /fast mover/);
  const none = Object.fromEntries(
    detailFor({ kind: "gaia", star: gaiaStar(5, null) }).rows,
  );
  assert.match(none.Distance, /no parallax/);
  const wise = Object.fromEntries(
    detailFor({ kind: "wise", source: wiseSource("w", [], true) }).rows,
  );
  assert.equal(wise.Colour, "3.40 W1−W2");
  assert.match(wise.Status, /Cold candidate/);
});

test("changeLabel separates known objects from cold candidates", () => {
  const c = {
    label: "candidate_signal",
    gaia_match: null,
  } as CandidateDetection;
  assert.equal(
    changeLabel({ ...c, label: "catalogued_object" }),
    "Catalogued object",
  );
  assert.equal(changeLabel(c), "Cold candidate (no Gaia)");
  assert.equal(
    changeLabel({
      ...c,
      gaia_match: { source_id: "1", g_mag: 9, dist_arcsec: 6 },
    }),
    "Candidate signal",
  );
});

test("alignmentFor returns the real row, or a labelled simulated offset", () => {
  const alignment: Alignment = {
    patch_id: 1,
    detector: 3,
    size: "medium",
    epochs: [
      {
        epoch_index: 1,
        mid_mjd: 61000,
        stars_used: 12,
        median_dx_px: 0.1,
        median_dy_px: 0,
        rms_arcsec: 0.4,
        status: "ok",
      },
    ],
  };
  assert.equal(alignmentFor(alignment, 1, false)?.status, "ok");
  assert.equal(alignmentFor(alignment, 2, false), null);
  const sim = alignmentFor(alignment, 1, true)!;
  assert.equal(sim.status, "offset_warning");
  assert.equal(sim.simulated, true);
  assert.equal(sim.stars_used, 12);
});
