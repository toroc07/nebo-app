import { test } from "node:test";
import assert from "node:assert/strict";
import {
  raToParts,
  decToParts,
  partsToRa,
  partsToDec,
  stepRa,
  stepDec,
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
