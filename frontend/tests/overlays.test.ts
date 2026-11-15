import { test } from "node:test";
import assert from "node:assert/strict";
import type { CandidateDetection, CandidatesResponse } from "../lib/api";
import type { GaiaStar } from "../lib/lab/gaia";
import {
  alignmentFor,
  changeLabel,
  changesSummary,
  detailFor,
  isPreloaded,
  labelledChanges,
  MAX_CHANGE_LABELS,
  layerLine,
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
    classification: "candidate_signal",
    gaia_match: null,
  } as CandidateDetection;
  assert.equal(
    changeLabel({ ...c, classification: "catalogued_object" }),
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

test("layerLine explains an empty or failed layer", () => {
  assert.equal(layerLine("CatWISE", { error: "IRSA did not answer." }, "sources"), "CatWISE: IRSA did not answer.");
  assert.equal(layerLine("CatWISE", null, "sources"), "CatWISE: loading…");
  assert.equal(layerLine("CatWISE", { value: {} }, "sources", 0, 0), "CatWISE: no sources returned for this field");
  assert.equal(layerLine("Gaia", { value: {} }, "stars", 5, 0), "Gaia: 5 stars, none inside this image");
  assert.equal(layerLine("Gaia", { value: {} }, "stars", 138, 120), "Gaia: 120 stars on this image");
});

test("isPreloaded matches within 30 arcsec, across RA 0", () => {
  const patches = [{ ra: 359.999, dec: 0 }];
  assert.equal(isPreloaded({ ra: 0.004, dec: 0 }, patches), true); // 18″ away across RA 0
  assert.equal(isPreloaded({ ra: 0.02, dec: 0 }, patches), false); // 76″
  assert.equal(isPreloaded({ ra: 359.999, dec: 1 }, patches), false);
});

test("labelledChanges labels every cold candidate and the strongest others", () => {
  const change = (x: number, snr: number, classification: CandidateDetection["classification"], gaia = true) =>
    ({ x, y: 0, snr, classification, gaia_match: gaia ? { source_id: "g", g_mag: 9, dist_arcsec: 1 } : null }) as CandidateDetection;
  const many = Array.from({ length: 20 }, (_, i) => change(i, i, "candidate_signal"));
  const cold = change(99, 1, "candidate_signal", false);
  const keys = labelledChanges([...many, cold]);
  assert.equal(keys.size, MAX_CHANGE_LABELS);
  assert.ok(keys.has("99,0")); // the weak cold candidate still gets its badge
  assert.ok(keys.has("19,0") && !keys.has("0,0")); // strongest first
});

test("likely systematics are labelled as such, summarised apart and never badged", () => {
  const change = (x: number, snr: number, classification: CandidateDetection["classification"]) =>
    ({ x, y: 0, snr, classification, gaia_match: { source_id: "g", g_mag: 9, dist_arcsec: 1 } }) as CandidateDetection;
  const systematic = change(1, 500, "catalogued_systematic");
  assert.equal(changeLabel(systematic), "Catalogued · likely PSF/λ systematic");
  const keys = labelledChanges([systematic, change(2, 10, "catalogued_object")]);
  assert.ok(keys.has("2,0") && !keys.has("1,0"));

  const res = {
    candidates: [change(2, 10, "catalogued_object"), systematic],
    truncated: false,
    counts: { detected: 14, changes: 3, likely_systematic: 11 },
  } as CandidatesResponse;
  assert.equal(changesSummary(res), "3 changes · 11 likely systematic");
  // Older API without counts: fall back to the listed candidates, "+" when cut at the cap.
  assert.equal(changesSummary({ ...res, counts: undefined, truncated: true }), "1+ change · 1 likely systematic");
  assert.equal(changesSummary({ ...res, counts: { detected: 1, changes: 1, likely_systematic: 0 } }), "1 change");
});
