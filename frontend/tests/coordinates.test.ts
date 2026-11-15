import { test } from "node:test";
import assert from "node:assert/strict";
import {
  raToParts,
  decToParts,
  partsToRa,
  partsToDec,
  stepRa,
  stepDec,
  gmstDeg,
  subPoint,
  angularDistance,
  hammer,
  hammerInverse,
  fovToFraction,
  fractionToFov,
  wrap180,
} from "../lib/coordinates";

const near = (a: number | null, b: number, tol = 1e-6) =>
  assert.ok(a !== null && Math.abs(a - b) <= tol, `${a} vs ${b}`);

test("RA round-trips through h/m/s parts", () => {
  // 02h 19m 10.88s, the value shown in the design reference.
  const ra = (2 + 19 / 60 + 10.88 / 3600) * 15;
  assert.deepEqual(raToParts(ra), { h: "02", m: "19", s: "10.88" });
  near(partsToRa(raToParts(ra)), ra, 1e-6);
});

test("Dec round-trips through signed d/m/s parts", () => {
  const dec = -(4 + 44 / 60 + 39.2 / 3600);
  assert.deepEqual(decToParts(dec), { sign: "-", d: "04", m: "44", s: "39.2" });
  near(partsToDec(decToParts(dec)), dec, 1e-6);
});

test("rounding carries into the next unit instead of showing 60", () => {
  assert.deepEqual(raToParts(359.99999999), { h: "00", m: "00", s: "00.00" });
  assert.deepEqual(decToParts(4.99999999), { sign: "+", d: "05", m: "00", s: "00.0" });
});

test("a value that rounds to zero is +00, never −00", () => {
  assert.equal(decToParts(-0.000001).sign, "+");
});

test("out-of-range or empty boxes are rejected", () => {
  assert.equal(partsToRa({ h: "24", m: "00", s: "0" }), null);
  assert.equal(partsToRa({ h: "01", m: "60", s: "0" }), null);
  assert.equal(partsToRa({ h: "01", m: "00", s: "60" }), null);
  assert.equal(partsToRa({ h: "", m: "00", s: "0" }), null);
  assert.equal(partsToRa({ h: "1.5", m: "00", s: "0" }), null);
  assert.equal(partsToDec({ sign: "+", d: "90", m: "00", s: "01" }), null);
  assert.equal(partsToDec({ sign: "-", d: "x", m: "00", s: "0" }), null);
  near(partsToDec({ sign: "-", d: "90", m: "0", s: "0" }), -90);
});

test("a decimal comma is accepted in the seconds box", () => {
  near(partsToRa({ h: "0", m: "0", s: "1,5" }), (1.5 / 3600) * 15);
});

test("stepping carries and wraps RA, and clamps Dec at the poles", () => {
  near(stepRa(359.9, "h", 1), 14.9);
  near(stepRa(0, "m", -1), 360 - 0.25);
  assert.equal(stepDec(89.5, "d", 1), 90);
  assert.equal(stepDec(-89.5, "d", -1), -90);
});

test("GMST matches Meeus example 12.a (1987-04-10 0h UT = 13h10m46.3668s)", () => {
  const expected = (13 + 10 / 60 + 46.3668 / 3600) * 15;
  near(gmstDeg(new Date(Date.UTC(1987, 3, 10, 0, 0, 0))), expected, 1e-4);
});

test("the zenith point has latitude = Dec and drifts west 15° per sidereal hour", () => {
  const t0 = new Date(Date.UTC(2026, 10, 14, 0, 0, 0));
  const a = subPoint(269.446, 4.769, t0);
  assert.equal(a.lat, 4.769);
  // One sidereal hour later the same star is overhead 15° further west.
  const b = subPoint(269.446, 4.769, new Date(t0.getTime() + 3590170));
  near(wrap180(a.lon - b.lon), 15, 1e-3);
});

test("a star is overhead at Greenwich when its RA equals GMST", () => {
  const t = new Date(Date.UTC(2026, 0, 1, 6, 0, 0));
  near(subPoint(gmstDeg(t), 51.48, t).lon, 0, 1e-9);
});

test("angular distance: poles, equator and tiny separations", () => {
  near(angularDistance(0, 90, 123, -90), 180, 1e-9);
  near(angularDistance(10, 0, 20, 0), 10, 1e-9);
  near(angularDistance(100, 30, 100, 30 + 1 / 3600), 1 / 3600, 1e-9);
});

test("Hammer projection round-trips and keeps east on the left", () => {
  for (const [ra, dec] of [[0.1, 0], [90, 45], [180, 0], [269.446, 4.769], [330, -56.8], [10, -89]]) {
    const p = hammer(ra, dec);
    const back = hammerInverse(p.x, p.y)!;
    near(angularDistance(ra, dec, back.ra, back.dec), 0, 1e-6);
  }
  assert.ok(hammer(190, 0).x < hammer(170, 0).x, "larger RA is further left");
  assert.equal(hammerInverse(0.9, 0.9), null);
});

test("FOV gauge scale is logarithmic and invertible", () => {
  assert.equal(fovToFraction(0.1), 0);
  assert.equal(fovToFraction(180), 1);
  near(fractionToFov(fovToFraction(8)), 8, 1e-9);
  near(fovToFraction(Math.sqrt(0.1 * 180)), 0.5, 1e-9);
});
