import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chooseLevel,
  fieldOfViewArcmin,
  levelOffset,
  visibleWorldRect,
  type Level,
  type Rect,
} from "../lib/lab/fov";
import { fillWidthView, zoomAt } from "../lib/lab/viewport";

const levels: Level[] = [
  { name: "small", width: 31, height: 31 },
  { name: "medium", width: 59, height: 59 },
  { name: "large", width: 147, height: 147 },
];
const world = { width: 147, height: 147 };
const screen = { width: 1280, height: 720 };

const near = (a: number, b: number, tol = 1e-9) =>
  assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

/** A square of `side` world pixels centred on the world centre. */
const centred = (side: number): Rect => ({
  x0: 73.5 - side / 2,
  y0: 73.5 - side / 2,
  x1: 73.5 + side / 2,
  y1: 73.5 + side / 2,
});

test("smaller levels are centred in the world with integer offsets", () => {
  assert.deepEqual(levelOffset(world, levels[1]), { x: 44, y: 44 });
  assert.deepEqual(levelOffset(world, levels[0]), { x: 58, y: 58 });
  assert.deepEqual(levelOffset(world, levels[2]), { x: 0, y: 0 });
});

test("the smallest level that covers the view is chosen", () => {
  assert.equal(chooseLevel(levels, world, centred(20), null), "small");
  assert.equal(chooseLevel(levels, world, centred(40), null), "medium");
  assert.equal(chooseLevel(levels, world, centred(100), null), "large");
  // Larger than the world itself: the largest level is all there is.
  assert.equal(chooseLevel(levels, world, centred(400), null), "large");
});

test("a view exactly on a level's edge does not need the next level (float tolerance)", () => {
  assert.equal(chooseLevel(levels, world, centred(59 + 1e-9), null), "medium");
  assert.equal(chooseLevel(levels, world, centred(31), null), "small");
});

test("zooming out switches up as soon as the current level stops covering", () => {
  assert.equal(chooseLevel(levels, world, centred(59.5), "medium"), "large");
  assert.equal(chooseLevel(levels, world, centred(31.5), "small"), "medium");
});

test("zooming back in only shrinks with a margin (no flapping at the boundary)", () => {
  // 30 px fits the small level (31) but not with the 10% margin (27.9): stay on medium.
  assert.equal(chooseLevel(levels, world, centred(30), "medium"), "medium");
  assert.equal(chooseLevel(levels, world, centred(27), "medium"), "small");
  // A big view on large never shrinks to medium until it fits 90% of medium (53.1).
  assert.equal(chooseLevel(levels, world, centred(58), "large"), "large");
  assert.equal(chooseLevel(levels, world, centred(53), "large"), "medium");
});

test("a sequence of tiny movements around a boundary never flips the level", () => {
  let level = chooseLevel(levels, world, centred(58.9), null);
  assert.equal(level, "medium");
  const seen = new Set<string>();
  for (const side of [58.9, 58.5, 58.9, 58.0, 59.0, 57.5, 58.4]) {
    level = chooseLevel(levels, world, centred(side), level);
    seen.add(level);
  }
  assert.deepEqual([...seen], ["medium"]);
});

test("with a level missing, the ladder skips it", () => {
  const noMedium = levels.filter((l) => l.name !== "medium");
  assert.equal(chooseLevel(noMedium, world, centred(40), null), "large");
  assert.equal(chooseLevel(noMedium, world, centred(20), null), "small");
});

test("the starting view (medium filling the width) is served by the medium level", () => {
  const space = { ...world, focus: { width: 59, height: 59 } };
  const start = fillWidthView(screen, space);
  const visible = visibleWorldRect(start, screen, world);
  near(visible.x1 - visible.x0, 59, 1e-6);
  assert.equal(chooseLevel(levels, world, visible, null), "medium");
  assert.equal(chooseLevel(levels, world, visible, "medium"), "medium");
});

test("zooming in from the start reaches small; zooming out reaches large", () => {
  const space = { ...world, focus: { width: 59, height: 59 } };
  let view = fillWidthView(screen, space);
  const mid = { x: 640, y: 360 };
  let level = chooseLevel(
    levels,
    world,
    visibleWorldRect(view, screen, world),
    null,
  );
  const trail: string[] = [level];
  for (let i = 0; i < 4; i++) {
    view = zoomAt(view, 1.5, mid, screen, space);
    level = chooseLevel(
      levels,
      world,
      visibleWorldRect(view, screen, world),
      level,
    );
    trail.push(level);
  }
  assert.equal(trail.at(-1), "small", trail.join(" > "));
  for (let i = 0; i < 14; i++) {
    view = zoomAt(view, 1 / 1.5, mid, screen, space);
    level = chooseLevel(
      levels,
      world,
      visibleWorldRect(view, screen, world),
      level,
    );
  }
  assert.equal(level, "large");
  // Zoomed all the way out, the whole world is visible.
  const all = visibleWorldRect(view, screen, world);
  near(all.x1 - all.x0, 147, 1e-6);
});

test("the visible rect is clipped to the world", () => {
  const space = { ...world, focus: { width: 59, height: 59 } };
  const whole = zoomAt(
    fillWidthView(screen, space),
    0.001,
    { x: 640, y: 360 },
    screen,
    space,
  );
  const r = visibleWorldRect(whole, screen, world);
  assert.ok(r.x0 >= 0 && r.y0 >= 0 && r.x1 <= 147 && r.y1 <= 147);
});

test("field of view in arcminutes follows the zoom", () => {
  const space = { ...world, focus: { width: 59, height: 59 } };
  const start = fillWidthView(screen, space);
  const f = fieldOfViewArcmin(start, screen, 6.15);
  // The medium image (59 px x 6.15") spans the full screen width: 59 * 6.15 / 60 = 6.0475'.
  near(f.width, 6.0475, 1e-4);
  const zoomed = zoomAt(start, 2, { x: 640, y: 360 }, screen, space);
  near(fieldOfViewArcmin(zoomed, screen, 6.15).width, 6.0475 / 2, 1e-4);
});

test("the starting level follows the screen: wide -> medium, tall (phone) -> large", () => {
  const space = { ...world, focus: { width: 59, height: 59 } };
  const levelFor = (box: { width: number; height: number }) =>
    chooseLevel(
      levels,
      world,
      visibleWorldRect(fillWidthView(box, space), box, world),
      null,
    );
  assert.equal(levelFor({ width: 1895, height: 858 }), "medium");
  assert.equal(levelFor({ width: 800, height: 800 }), "medium");
  // A phone shows ~128 px of sky vertically; the medium image is 59 px tall, so it would leave
  // empty bars above and below that a first zoom would suddenly fill.
  assert.equal(levelFor({ width: 375, height: 812 }), "large");
});
