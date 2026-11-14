import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  gridFrom,
  pixelToSky,
  skyToPixel,
  formatRa,
  formatDec,
} from "../lib/lab/sky";

// `npm test` runs from frontend/, and the demo export lives in ../shared/demo.
function demo(name: string) {
  return JSON.parse(
    readFileSync(
      path.join(process.cwd(), "..", "shared", "demo", "timeline", name),
      "utf8",
    ),
  );
}

const near = (a: number, b: number, tol: number, label: string) =>
  assert.ok(Math.abs(a - b) <= tol, `${label}: ${a} vs ${b} (tol ${tol})`);

test("the central pixel is the patch centre", () => {
  const t = demo("barnards-star_d3_medium.json");
  const g = gridFrom(t);
  const p = pixelToSky(g, (g.width - 1) / 2, (g.height - 1) / 2);
  near(p.ra, t.patch.ra, 1e-9, "ra");
  near(p.dec, t.patch.dec, 1e-9, "dec");
});

test("pixelToSky reproduces the API's expected_position in every epoch", () => {
  for (const file of [
    "barnards-star_d3_medium.json",
    "wise-0855_d6_large.json",
    "r-draconis_d3_small.json",
  ]) {
    const t = demo(file);
    const g = gridFrom(t);
    for (const e of t.epochs) {
      const ep = e.expected_position;
      if (!ep) continue;
      const p = pixelToSky(g, ep.x, ep.y);
      // The API rounds x/y to 2 decimals (~0.01 px = 0.06″ = 1.7e-5°).
      near(p.ra, ep.ra, 5e-5, `${file} ra`);
      near(p.dec, ep.dec, 5e-5, `${file} dec`);
    }
  }
});

test("image corners match sector.corners: top-left is NE, top-right is NW", () => {
  const t = demo("barnards-star_d3_medium.json");
  const g = gridFrom(t);
  const { NE, NW, SE, SW } = t.sector.corners as Record<
    string,
    [number, number]
  >;
  // Corners are pixel edges, half a pixel beyond the first/last pixel centre.
  const tl = pixelToSky(g, -0.5, -0.5);
  const tr = pixelToSky(g, g.width - 0.5, -0.5);
  const bl = pixelToSky(g, -0.5, g.height - 0.5);
  const br = pixelToSky(g, g.width - 0.5, g.height - 0.5);
  for (const [got, want, label] of [
    [tl, NE, "top-left = NE"],
    [tr, NW, "top-right = NW"],
    [bl, SE, "bottom-left = SE"],
    [br, SW, "bottom-right = SW"],
  ] as const) {
    near(got.ra, want[0], 2e-4, `${label} ra`);
    near(got.dec, want[1], 2e-4, `${label} dec`);
  }
});

test("east is to the left and north is up", () => {
  const g = gridFrom(demo("barnards-star_d3_medium.json"));
  const mid = (g.width - 1) / 2;
  assert.ok(pixelToSky(g, mid - 5, mid).ra > pixelToSky(g, mid + 5, mid).ra);
  assert.ok(pixelToSky(g, mid, mid - 5).dec > pixelToSky(g, mid, mid + 5).dec);
});

test("skyToPixel inverts pixelToSky, including at high declination", () => {
  for (const file of [
    "barnards-star_d3_large.json",
    "r-draconis_d3_large.json",
  ]) {
    const g = gridFrom(demo(file));
    for (const [x, y] of [
      [0, 0],
      [g.width - 1, 3],
      [20.25, g.height - 1],
      [(g.width - 1) / 2, (g.height - 1) / 2],
    ]) {
      const p = pixelToSky(g, x, y);
      const back = skyToPixel(g, p.ra, p.dec);
      near(back.x, x, 1e-6, `${file} x`);
      near(back.y, y, 1e-6, `${file} y`);
    }
  }
});

test("RA wraps through 0/360 without breaking", () => {
  const g = { ra: 0.001, dec: 10, width: 59, height: 59, scaleArcsec: 6.15 };
  // The right edge is west, so RA decreases and crosses 0 into 359.x.
  const p = pixelToSky(g, 58, 29);
  assert.ok(p.ra > 359 && p.ra < 360, `ra ${p.ra}`);
  near(
    p.ra,
    360 + 0.001 - (29 * 6.15) / 3600 / Math.cos((10 * Math.PI) / 180),
    1e-4,
    "ra",
  );
  const back = skyToPixel(g, p.ra, p.dec);
  near(back.x, 58, 1e-6, "x");
  near(back.y, 29, 1e-6, "y");
});

test("sexagesimal formatting rounds and carries correctly", () => {
  assert.equal(formatRa(0), "0h 00m 00.00s");
  assert.equal(formatRa(269.446223), "17h 57m 47.09s");
  // 59.995 s must carry into the next minute, not print "60.00s".
  assert.equal(
    formatRa((17 * 3600 + 57 * 60 + 59.999) / 240),
    "17h 58m 00.00s",
  );
  assert.equal(formatRa(359.9999999), "0h 00m 00.00s");
  assert.equal(formatDec(4.76878), "+04° 46′ 07.6″");
  assert.equal(formatDec(-56.800786), "−56° 48′ 02.8″");
  assert.equal(formatDec(-0.0000001), "+00° 00′ 00.0″");
  assert.equal(formatDec(59.99999), "+60° 00′ 00.0″");
});
