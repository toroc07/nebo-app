/**
 * Sexagesimal ↔ decimal conversion for the cockpit coordinate panel.
 *
 * The panel edits each part (hours, minutes, seconds…) in its own box, so the
 * conversions work on string parts: a half-typed value must survive a render
 * without being normalised under the user's cursor.
 */

export type RaParts = { h: string; m: string; s: string };
export type DecParts = { sign: "+" | "-"; d: string; m: string; s: string };

const two = (n: number) => String(n).padStart(2, "0");

export function normalizeRa(ra: number): number {
  return ((ra % 360) + 360) % 360;
}

/** RA in degrees → `02 h 19 m 10.88 s` parts (seconds to 0.01 s). */
export function raToParts(raDeg: number): RaParts {
  // Integer hundredths of a second keep the carry into minutes and hours exact.
  const total = Math.round((normalizeRa(raDeg) / 15) * 3600 * 100) % (24 * 3600 * 100);
  const h = Math.floor(total / 360000);
  const m = Math.floor((total % 360000) / 6000);
  const s = (total % 6000) / 100;
  return { h: two(h), m: two(m), s: s.toFixed(2).padStart(5, "0") };
}

/** Dec in degrees → `+04 ° 44 ′ 39.2 ″` parts (seconds to 0.1″). */
export function decToParts(decDeg: number): DecParts {
  const total = Math.round(Math.abs(decDeg) * 3600 * 10);
  const d = Math.floor(total / 36000);
  const m = Math.floor((total % 36000) / 600);
  const s = (total % 600) / 10;
  // A value that rounds to zero is +00, never a negative zero.
  const sign = decDeg < 0 && total > 0 ? "-" : "+";
  return { sign, d: two(d), m: two(m), s: s.toFixed(1).padStart(4, "0") };
}

/** Parses one box; empty or non-numeric text is not a value. */
function part(text: string): number | null {
  const t = text.trim().replace(",", ".");
  if (t === "" || !/^\d+(\.\d*)?$/.test(t)) return null;
  return Number(t);
}

/** RA parts → degrees, or null when a box is empty or out of range. */
export function partsToRa(p: RaParts): number | null {
  const h = part(p.h), m = part(p.m), s = part(p.s);
  if (h === null || m === null || s === null) return null;
  if (!Number.isInteger(h) || !Number.isInteger(m) || h > 23 || m > 59 || s >= 60) return null;
  return (h + m / 60 + s / 3600) * 15;
}

/** Dec parts → degrees, or null when a box is empty or out of range. */
export function partsToDec(p: DecParts): number | null {
  const d = part(p.d), m = part(p.m), s = part(p.s);
  if (d === null || m === null || s === null) return null;
  if (!Number.isInteger(d) || !Number.isInteger(m) || m > 59 || s >= 60) return null;
  const value = d + m / 60 + s / 3600;
  if (value > 90) return null;
  return p.sign === "-" ? -value : value;
}

/**
 * Moves RA by a number of steps of the given unit, wrapping around 24 h.
 * Stepping through degrees (not the separate boxes) makes 59 m + 1 m carry into the hour.
 */
export function stepRa(raDeg: number, unit: "h" | "m" | "s", steps: number): number {
  const size = { h: 15, m: 15 / 60, s: 15 / 3600 }[unit];
  return normalizeRa(raDeg + size * steps);
}

/** Moves Dec by steps of the given unit, clamped to the poles. */
export function stepDec(decDeg: number, unit: "d" | "m" | "s", steps: number): number {
  const size = { d: 1, m: 1 / 60, s: 1 / 3600 }[unit];
  return Math.max(-90, Math.min(90, decDeg + size * steps));
}
