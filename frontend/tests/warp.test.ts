import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LOOK_UP_Y,
  MOTION,
  REDUCED,
  WarpController,
  arriveStart,
  frameAt,
  isDestinationReady,
  isExploreReady,
  viewerStatus,
  type Timeline,
} from "../lib/warp";
import {
  STREAK_COUNT,
  Z_NEAR,
  createStreaks,
  mulberry32,
  projectStreak,
  stepStreaks,
} from "../lib/warp-render";

const near = (a: number, b: number, tol = 1e-9) =>
  assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

const waiting: Timeline = { target: "explore", launchedAt: 10, readyAt: null };

test("the tunnel starts dark and still, and ends cruising at full speed", () => {
  const start = frameAt(waiting, 10, MOTION);
  assert.equal(start.phase, "launch");
  near(start.opacity, 0);
  near(start.speed, 0);
  near(start.centerY, 0.5);

  const cruise = frameAt(waiting, 10 + MOTION.launch + 0.5, MOTION);
  assert.equal(cruise.phase, "cruise");
  near(cruise.opacity, 1);
  near(cruise.speed, 1);
  // The camera has tipped up: the vanishing point sits above the middle of the screen.
  near(cruise.centerY, LOOK_UP_Y);
  assert.ok(cruise.centerY < 0.5);
});

test("it keeps cruising for as long as the data has not arrived", () => {
  for (const t of [3, 6, 11.9]) {
    const f = frameAt(waiting, 10 + t, MOTION);
    assert.equal(f.phase, "cruise", `t=${t}`);
    near(f.opacity, 1);
  }
});

test("data that arrives instantly still gets the minimum time on screen", () => {
  const instant: Timeline = {
    target: "explore",
    launchedAt: 10,
    readyAt: 10.1,
  };
  near(arriveStart(instant, MOTION), MOTION.minTotal);
  assert.equal(
    frameAt(instant, 10 + MOTION.minTotal - 0.01, MOTION).phase,
    "cruise",
  );
  assert.equal(
    frameAt(instant, 10 + MOTION.minTotal + 0.01, MOTION).phase,
    "arrive",
  );
});

test("slow data delays the arrival until it is ready", () => {
  const slow: Timeline = { target: "explore", launchedAt: 10, readyAt: 14.5 };
  near(arriveStart(slow, MOTION), 4.5);
  assert.equal(frameAt(slow, 10 + 4.4, MOTION).phase, "cruise");
  assert.equal(frameAt(slow, 10 + 4.6, MOTION).phase, "arrive");
});

test("the arrival decelerates first and fades afterwards, then finishes", () => {
  const tl: Timeline = { target: "explore", launchedAt: 0, readyAt: 0.5 };
  const start = MOTION.minTotal;
  let lastSpeed = 1;
  let lastOpacity = 1;
  for (let i = 0; i <= 20; i++) {
    const f = frameAt(tl, start + (MOTION.arrive * i) / 20 - 1e-6, MOTION);
    assert.ok(f.speed <= lastSpeed + 1e-9, "speed never increases");
    assert.ok(f.opacity <= lastOpacity + 1e-9, "opacity never increases");
    lastSpeed = f.speed;
    lastOpacity = f.opacity;
  }
  // Early in the arrival it is already slower but still fully visible...
  const early = frameAt(tl, start + MOTION.arrive * 0.2, MOTION);
  assert.ok(early.speed < 0.7);
  near(early.opacity, 1);
  // ...and by the end it is gone.
  const end = frameAt(tl, start + MOTION.arrive, MOTION);
  assert.equal(end.phase, "done");
  near(end.opacity, 0);
});

test("the text is gone before the viewer shows through, so it never sits on the interface", () => {
  const tl: Timeline = { target: "explore", launchedAt: 0, readyAt: 0.5 };
  const start = MOTION.minTotal;
  // Hidden on the very first frame, shown once the tunnel is moving.
  near(frameAt(tl, 0, MOTION).labelOpacity, 0);
  near(frameAt(tl, 1.0, MOTION).labelOpacity, 1);
  // Fully gone a quarter of the way into the arrival...
  near(frameAt(tl, start + MOTION.arrive * 0.25, MOTION).labelOpacity, 0);
  // ...which is before the overlay has even started to become transparent.
  const quarter = frameAt(tl, start + MOTION.arrive * 0.25, MOTION);
  assert.ok(quarter.opacity > 0.95, `overlay opacity ${quarter.opacity}`);
  // And it never reappears.
  let last = 1;
  for (let i = 0; i <= 40; i++) {
    const f = frameAt(tl, start + (MOTION.arrive * i) / 40 - 1e-6, MOTION);
    assert.ok(f.labelOpacity <= last + 1e-9);
    last = f.labelOpacity;
  }
});

test("a page that never loads cannot trap the user: the arrival is forced", () => {
  assert.equal(
    frameAt(waiting, 10 + MOTION.maxTotal - 0.1, MOTION).phase,
    "cruise",
  );
  assert.equal(
    frameAt(waiting, 10 + MOTION.maxTotal + 0.1, MOTION).phase,
    "arrive",
  );
  assert.equal(
    frameAt(waiting, 10 + MOTION.maxTotal + MOTION.arrive + 0.1, MOTION).phase,
    "done",
  );
});

test("every frame stays inside its valid range", () => {
  for (const timing of [MOTION, REDUCED]) {
    for (const readyAt of [null, 10.2, 12, 20]) {
      const tl: Timeline = { target: "explore", launchedAt: 10, readyAt };
      for (let t = -1; t < 26; t += 0.17) {
        const f = frameAt(tl, 10 + t, timing);
        assert.ok(f.opacity >= 0 && f.opacity <= 1, `opacity ${f.opacity}`);
        assert.ok(f.speed >= 0 && f.speed <= 1, `speed ${f.speed}`);
        assert.ok(
          f.centerY >= LOOK_UP_Y - 1e-9 && f.centerY <= 0.5 + 1e-9,
          `centerY ${f.centerY}`,
        );
        assert.ok(f.zoom >= 1 && f.zoom <= 1.18 + 1e-9, `zoom ${f.zoom}`);
        assert.ok(
          f.labelOpacity >= 0 && f.labelOpacity <= 1,
          `label ${f.labelOpacity}`,
        );
      }
    }
  }
});

test("reduced motion is much shorter and never goes fast", () => {
  assert.ok(REDUCED.minTotal < MOTION.minTotal / 2);
  assert.ok(REDUCED.arrive < MOTION.arrive);
});

test("the controller ignores a second launch and only the first ready counts", () => {
  const c = new WarpController();
  let notified = 0;
  c.subscribe(() => notified++);
  c.launch(5, "explore");
  c.launch(6, "explore");
  assert.equal(c.timeline()?.launchedAt, 5);
  assert.equal(notified, 1);
  assert.equal(c.isReady(), false);
  c.markReady(7);
  c.markReady(9);
  assert.equal(c.timeline()?.readyAt, 7);
  assert.equal(c.isReady(), true);
  c.finish();
  assert.equal(c.isActive(), false);
  assert.equal(notified, 2);
  // Marking ready with nothing running does nothing and does not throw.
  c.markReady(10);
  assert.equal(c.isActive(), false);
  // And a new transition can start afterwards.
  c.launch(20, "explore");
  assert.equal(c.timeline()?.launchedAt, 20);
});

// --- readiness detection -------------------------------------------------------------------

type El = {
  complete?: boolean;
  naturalWidth?: number;
  textContent: string | null;
};
const page = (found: Record<string, El | null>) => ({
  querySelector: (selector: string) => found[selector] ?? null,
});
const STATUS = 'main [role="status"]:not([data-warp] *)';

test("the viewer's own loading message is passed through", () => {
  assert.equal(
    viewerStatus(
      page({ [STATUS]: { textContent: " Building: downloading 3/24 " } }),
    ),
    "Building: downloading 3/24",
  );
  assert.equal(viewerStatus(page({})), "");
});

// --- sky globe readiness ---------------------------------------------------------------------

const OPEN = ".explorer-grid:not([hidden])";
const HOST = `${OPEN} .aladin-host`;
const MESSAGE = `${OPEN} .sky-message`;
const RETRY = `${OPEN} .sky-message button`;

test("the globe is ready once its map has mounted and stopped loading", () => {
  const ready = page({ [HOST]: { textContent: "" } });
  assert.equal(isExploreReady(ready), true);
  // Mounted but still showing "Loading sky map…".
  const loading = page({
    [HOST]: { textContent: "" },
    [MESSAGE]: { textContent: "Loading sky map…" },
  });
  assert.equal(isExploreReady(loading), false);
});

test("a failed map counts as ready, so the user sees the error and not a tunnel", () => {
  const failed = page({
    [HOST]: { textContent: "" },
    [MESSAGE]: { textContent: "The sky map could not be loaded." },
    [RETRY]: { textContent: "Retry map" },
  });
  assert.equal(isExploreReady(failed), true);
});

test("the globe is not ready while the map's code is still downloading or the view is hidden", () => {
  // Next shows its own "Loading sky…" placeholder and there is no map host yet.
  assert.equal(isExploreReady(page({})), false);
  // A hidden explorer (another view is open) never matches the selector.
  assert.equal(
    isExploreReady(
      page({ ".explorer-grid .aladin-host": { textContent: "" } }),
    ),
    false,
  );
});

test("the destination is judged by its own page", () => {
  assert.equal(isDestinationReady("explore", page({ [HOST]: { textContent: "" } })), true);
  assert.equal(isDestinationReady("explore", page({})), false);
});

test("the controller remembers where it is heading", () => {
  const c = new WarpController();
  c.launch(1, "explore");
  assert.equal(c.timeline()?.target, "explore");
});

// --- star field -----------------------------------------------------------------------------

test("the star field is reproducible and fills the whole depth", () => {
  const a = createStreaks(STREAK_COUNT, mulberry32(7));
  const b = createStreaks(STREAK_COUNT, mulberry32(7));
  assert.deepEqual(a, b);
  assert.equal(a.length, STREAK_COUNT);
  for (const s of a) {
    assert.ok(s.z >= Z_NEAR && s.z <= 1);
    assert.ok(s.radius >= 0.05, "the middle of the tunnel stays dark");
  }
  assert.ok(
    Math.min(...a.map((s) => s.z)) < 0.3 &&
      Math.max(...a.map((s) => s.z)) > 0.7,
  );
});

test("stars fly towards the camera and are respawned far away when they pass it", () => {
  const rng = mulberry32(3);
  const stars = createStreaks(200, rng);
  const before = stars.map((s) => s.z);
  stepStreaks(stars, 0.1, 1, rng);
  stars.forEach((s, i) =>
    assert.ok(
      s.z < before[i] || s.z === 1,
      "closer, or respawned at the far end",
    ),
  );
  for (let i = 0; i < 400; i++) stepStreaks(stars, 0.05, 1, rng);
  for (const s of stars) assert.ok(s.z >= Z_NEAR && s.z <= 1, `z ${s.z}`);
});

test("at rest the stars barely move; at speed they move a lot", () => {
  // A short step, ignoring the few stars that passed the camera and were respawned far away
  // (they jump back to z = 1, which would pollute the average).
  const advance = (speed: number) => {
    const stars = createStreaks(300, mulberry32(1));
    const before = stars.map((s) => s.z);
    stepStreaks(stars, 0.1, speed, mulberry32(9));
    const deltas = stars.map((s, i) => before[i] - s.z).filter((d) => d >= 0);
    return deltas.reduce((sum, d) => sum + d, 0) / deltas.length;
  };
  assert.ok(advance(0) < 0.01, `at rest ${advance(0)}`);
  assert.ok(advance(1) > 0.08, `at speed ${advance(1)}`);
});

test("a streak is a dot at rest and a long ray at speed, along the line to the vanishing point", () => {
  const star = { angle: 0.7, radius: 0.4, z: 0.4, tone: 1 as const, size: 1 };
  const [w, h, cx, cy] = [1920, 1080, 960, 324];
  const still = projectStreak(star, 0, 0, w, h, cx, cy)!;
  const fast = projectStreak(star, 1, 0, w, h, cx, cy)!;
  const len = (s: { x0: number; y0: number; x1: number; y1: number }) =>
    Math.hypot(s.x1 - s.x0, s.y1 - s.y0);
  near(len(still), 0, 1e-6);
  assert.ok(len(fast) > 50, `long ray ${len(fast)}`);
  // The tail is closer to the vanishing point than the head, on the same ray.
  assert.ok(
    Math.hypot(fast.x0 - cx, fast.y0 - cy) <
      Math.hypot(fast.x1 - cx, fast.y1 - cy),
  );
  near(Math.atan2(fast.y1 - cy, fast.x1 - cx), 0.7, 1e-9);
  near(Math.atan2(fast.y0 - cy, fast.x0 - cx), 0.7, 1e-9);
});

test("rays get brighter and thicker as they approach, and off-screen or tiny ones are skipped", () => {
  const base = { angle: 1, radius: 0.5, tone: 0 as const, size: 1 };
  const far = projectStreak({ ...base, z: 0.9 }, 1, 0, 1920, 1080, 960, 540)!;
  const close = projectStreak({ ...base, z: 0.2 }, 1, 0, 1920, 1080, 960, 540)!;
  assert.ok(close.width > far.width && close.alpha > far.alpha);
  assert.ok(far.alpha > 0 && close.alpha <= 1);
  // Far outside the screen (a star that is about to pass the camera at a wide angle).
  assert.equal(
    projectStreak(
      { ...base, radius: 1.4, z: Z_NEAR },
      1,
      0,
      1920,
      1080,
      960,
      540,
    ),
    null,
  );
  // A star so close to the axis and so far away that it is under one pixel is skipped.
  assert.equal(
    projectStreak({ ...base, radius: 0.005, z: 1 }, 0, 0, 100, 100, 50, 50),
    null,
  );
});
