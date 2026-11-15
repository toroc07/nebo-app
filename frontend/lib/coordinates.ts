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

const RAD = Math.PI / 180;

/** Wraps a longitude into (−180°, 180°]. */
export function wrap180(deg: number): number {
  const d = ((((deg + 180) % 360) + 360) % 360) - 180;
  return d === -180 ? 180 : d;
}

/**
 * Greenwich mean sidereal time in degrees (Meeus, Astronomical Algorithms, eq. 12.4).
 * Accurate to well under a second of time for dates near the present.
 */
export function gmstDeg(date: Date): number {
  const jd = date.getTime() / 86400000 + 2440587.5;
  const t = (jd - 2451545) / 36525;
  return normalizeRa(
    280.46061837 + 360.98564736629 * (jd - 2451545) + 0.000387933 * t * t - (t * t * t) / 38710000,
  );
}

/**
 * The point on Earth where a sky position is at the zenith right now: latitude = Dec,
 * longitude = RA − GMST. The Earth turns under the sky, so the point drifts west 15°/h.
 */
export function subPoint(raDeg: number, decDeg: number, date: Date): { lat: number; lon: number } {
  return { lat: decDeg, lon: wrap180(raDeg - gmstDeg(date)) };
}

/** A catalogued object this close to the map centre counts as "at the map centre" (3′, a small field). */
export const AT_MAP_CENTRE_DEG = 0.05;

/** Great-circle separation between two sky positions, in degrees (haversine, stable at small angles). */
export function angularDistance(ra1: number, dec1: number, ra2: number, dec2: number): number {
  const h =
    Math.sin(((dec2 - dec1) * RAD) / 2) ** 2 +
    Math.cos(dec1 * RAD) * Math.cos(dec2 * RAD) * Math.sin(((ra2 - ra1) * RAD) / 2) ** 2;
  return (2 * Math.asin(Math.min(1, Math.sqrt(h)))) / RAD;
}

/*
 * Hammer equal-area all-sky projection, centred on RA 12 h with east to the left, as on the
 * sky map. Output is normalised to x ∈ [−1, 1], y ∈ [−1, 1] (north up). Hammer is used rather
 * than Aitoff because it has a closed-form inverse, which turns a click into a position.
 */
export function hammer(raDeg: number, decDeg: number): { x: number; y: number } {
  const l = -wrap180(raDeg - 180) * RAD; // east (larger RA) to the left
  const b = decDeg * RAD;
  const k = Math.sqrt(1 + Math.cos(b) * Math.cos(l / 2));
  return {
    x: (2 * Math.SQRT2 * Math.cos(b) * Math.sin(l / 2)) / k / (2 * Math.SQRT2),
    y: (Math.SQRT2 * Math.sin(b)) / k / Math.SQRT2,
  };
}

/** Inverse of `hammer`; null outside the ellipse. */
export function hammerInverse(x: number, y: number): { ra: number; dec: number } | null {
  if (x * x + y * y > 1) return null;
  const X = x * 2 * Math.SQRT2;
  const Y = y * Math.SQRT2;
  const z = Math.sqrt(1 - (X / 4) ** 2 - (Y / 2) ** 2);
  const l = 2 * Math.atan2(z * X, 2 * (2 * z * z - 1));
  const b = Math.asin(Math.max(-1, Math.min(1, z * Y)));
  return { ra: normalizeRa(180 - l / RAD), dec: b / RAD };
}

/* Field of view on a log scale, so 0.1° and 180° are equally reachable on the gauge. */
export const FOV_MIN = 0.1;
export const FOV_MAX = 180;
export function fovToFraction(fov: number): number {
  const f = Math.max(FOV_MIN, Math.min(FOV_MAX, fov));
  return Math.log(f / FOV_MIN) / Math.log(FOV_MAX / FOV_MIN);
}
export function fractionToFov(t: number): number {
  return FOV_MIN * Math.pow(FOV_MAX / FOV_MIN, Math.max(0, Math.min(1, t)));
}
