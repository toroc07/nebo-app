import { test } from "node:test";
import assert from "node:assert/strict";
import { LANDMARKS } from "../lib/landmarks";

// The five Nebo targets (backend/app/targets.py): a landmark on top of one would hide it.
const NEBO_TARGETS = [
  { name: "Barnard's Star", ra: 269.446223, dec: 4.76878 },
  { name: "Epsilon Indi B", ra: 331.097073, dec: -56.800786 },
  { name: "WISE 0855-0714", ra: 133.75931, dec: -7.242145 },
  { name: "RW Aurigae", ra: 76.956587, dec: 30.40129 },
  { name: "R Draconis", ra: 248.16723, dec: 66.755024 },
];

const separationDeg = (a: { ra: number; dec: number }, b: { ra: number; dec: number }) => {
  const r = Math.PI / 180;
  const h =
    Math.sin(((b.dec - a.dec) * r) / 2) ** 2 +
    Math.cos(a.dec * r) * Math.cos(b.dec * r) * Math.sin(((b.ra - a.ra) * r) / 2) ** 2;
  return (2 * Math.asin(Math.min(1, Math.sqrt(h)))) / r;
};

test("landmarks have valid ICRS positions and unique names", () => {
  assert.ok(LANDMARKS.length >= 20);
  for (const l of LANDMARKS) {
    assert.ok(l.ra >= 0 && l.ra < 360, `${l.name} RA`);
    assert.ok(l.dec >= -90 && l.dec <= 90, `${l.name} Dec`);
    assert.ok(l.name.trim().length > 0);
  }
  assert.equal(new Set(LANDMARKS.map((l) => l.name)).size, LANDMARKS.length);
});

test("landmarks never duplicate or sit on a Nebo target", () => {
  for (const l of LANDMARKS)
    for (const t of NEBO_TARGETS) {
      assert.notEqual(l.name, t.name);
      assert.ok(separationDeg(l, t) > 0.5, `${l.name} is too close to ${t.name}`);
    }
});
