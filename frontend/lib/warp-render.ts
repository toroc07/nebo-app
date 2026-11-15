// Star streaks for the hyperspace tunnel. Pure maths, no canvas: the overlay only draws what
// `projectStreak` returns, which keeps the look testable.
//
// Every star sits at a fixed angle and distance from the flight axis and at a depth z (1 = far,
// near 0 = about to pass the camera). Perspective puts it at screen radius ~ radius / z, so as
// z shrinks it flies outward from the vanishing point, faster and faster. The streak is the
// segment between where it was a moment ago and where it is now, so it is as long as the speed
// is high: at rest the stars are dots, at full speed they are the long rays of the tunnel.

export type Rng = () => number;

/** Small deterministic generator, so tests (and the look) are reproducible. */
export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 0 white, 1 pale blue, 2 blue, 3 deep blue. */
export type Tone = 0 | 1 | 2 | 3;

export type Streak = {
  angle: number;
  /** Distance from the flight axis, in units of the screen's larger side. */
  radius: number;
  /** Depth: 1 far, `Z_NEAR` just before it flies past the camera. */
  z: number;
  tone: Tone;
  /** Thickness factor. */
  size: number;
};

export type Segment = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  width: number;
  alpha: number;
  tone: Tone;
};

export const STREAK_COUNT = 560;
/** Closer than this a star has passed the camera and is respawned far away. */
export const Z_NEAR = 0.035;
/** Depth units per second at full speed. A star crosses the whole depth in about a second. */
const Z_PER_SECOND = 0.95;
/** Depth units the streak trails behind the star at full speed. */
const TRAIL_DEPTH = 0.16;
/** How fast the whole field rolls at full speed, radians per second. */
const ROLL_PER_SECOND = 0.05;

// The reference tunnel is mostly blue-white with a few deep-blue rays.
function pickTone(rng: Rng): Tone {
  const r = rng();
  return r < 0.34 ? 0 : r < 0.68 ? 1 : r < 0.9 ? 2 : 3;
}

function spawn(rng: Rng, z: number): Streak {
  return {
    angle: rng() * Math.PI * 2,
    // The minimum keeps the middle of the tunnel dark, as in the reference. The exponent
    // gives more stars near the axis, where the rays are short and dense.
    radius: 0.05 + Math.pow(rng(), 1.6) * 1.35,
    z,
    tone: pickTone(rng),
    size: 0.5 + rng() * 1.1,
  };
}

export function createStreaks(count: number, rng: Rng): Streak[] {
  // Spread over the whole depth so the field is full from the first frame.
  return Array.from({ length: count }, () =>
    spawn(rng, Z_NEAR + rng() * (1 - Z_NEAR)),
  );
}

/**
 * Moves the stars `dt` seconds forward. `speed` is 0..1; a tiny drift remains at rest so the
 * stars shimmer instead of freezing. Returns the roll to add to every angle.
 */
export function stepStreaks(
  streaks: Streak[],
  dt: number,
  speed: number,
  rng: Rng,
): number {
  const dz = dt * (0.02 + Z_PER_SECOND * speed);
  for (let i = 0; i < streaks.length; i++) {
    const s = streaks[i];
    s.z -= dz;
    if (s.z < Z_NEAR) streaks[i] = spawn(rng, 1);
  }
  return dt * ROLL_PER_SECOND * speed;
}

/**
 * The line to draw for a star, or null if it is off screen or too small to see.
 * (cx, cy) is the vanishing point in pixels.
 */
export function projectStreak(
  s: Streak,
  speed: number,
  roll: number,
  width: number,
  height: number,
  cx: number,
  cy: number,
): Segment | null {
  const focal = Math.max(width, height) * 0.5;
  const rNow = (focal * s.radius) / s.z;
  const rBack = (focal * s.radius) / (s.z + TRAIL_DEPTH * speed);
  const reach = Math.hypot(width, height);
  if (rBack > reach * 1.2 || rNow < 0.6) return null;

  const a = s.angle + roll;
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  const near = 1 - s.z; // 0 far .. ~1 about to pass
  return {
    x0: cx + cos * rBack,
    y0: cy + sin * rBack,
    x1: cx + cos * rNow,
    y1: cy + sin * rNow,
    // Rays thicken as they approach, like the near ones in the reference.
    width: s.size * (0.5 + 2.2 * near * near),
    alpha:
      Math.min(1, near * 1.15 + 0.1) *
      (0.4 + 0.6 * Math.min(1, speed * 1.3 + 0.25)),
    tone: s.tone,
  };
}

export const TONE_RGB: Record<Tone, [number, number, number]> = {
  0: [255, 255, 255],
  1: [176, 218, 255],
  2: [78, 148, 255],
  3: [38, 88, 232],
};
