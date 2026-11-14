import { test } from "node:test";
import assert from "node:assert/strict";
import {
  containView,
  fillWidthView,
  scaleLimits,
  clampView,
  zoomAt,
  panBy,
  screenToImage,
  imageToScreen,
  wheelFactor,
} from "../lib/lab/viewport";

const screen = { width: 1280, height: 720 };
const portrait = { width: 390, height: 844 };
const image = { width: 59, height: 59 };

const near = (a: number, b: number, tol = 1e-9) =>
  assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

test("contain shows the whole image as large as possible and centred", () => {
  const v = containView(screen, image);
  near(v.scale, 720 / 59);
  // Limited by height, so the image touches top and bottom and is centred horizontally.
  near(v.ty, 0);
  near(v.tx, (1280 - 59 * v.scale) / 2);
  // A wide image is limited by width instead.
  const wide = containView(screen, { width: 200, height: 20 });
  near(wide.scale, 1280 / 200);
  near(wide.tx, 0);
});

test("fill-width spans the whole screen width and is centred vertically", () => {
  const v = fillWidthView(screen, image);
  near(v.scale, 1280 / 59);
  near(v.tx, 0);
  // A square image on a wide screen is taller than the screen: the overflow is split evenly.
  const h = 59 * v.scale;
  assert.ok(h > screen.height);
  near(v.ty, (screen.height - h) / 2);
  assert.ok(v.ty < 0);
  // The image centre stays at the screen centre.
  const c = imageToScreen(v, { x: 29.5, y: 29.5 });
  near(c.x, 640, 1e-6);
  near(c.y, 360, 1e-6);
});

test("on a portrait screen fill-width and contain are the same view", () => {
  const a = fillWidthView(portrait, image);
  const b = containView(portrait, image);
  near(a.scale, b.scale);
  near(a.tx, b.tx);
  near(a.ty, b.ty);
});

test("zoom keeps the image point under the cursor fixed", () => {
  const start = fillWidthView(screen, image);
  const anchor = { x: 700, y: 300 };
  const before = screenToImage(start, anchor);
  for (const factor of [1.5, 2, 0.8, 3]) {
    const next = zoomAt(start, factor, anchor, screen, image);
    const after = screenToImage(next, anchor);
    near(after.x, before.x, 1e-6);
    near(after.y, before.y, 1e-6);
  }
});

test("zoom-out stops at the whole image; zoom-in at the maximum", () => {
  const { min, max } = scaleLimits(screen, image);
  const start = fillWidthView(screen, image);
  near(min, containView(screen, image).scale);
  assert.ok(min < start.scale, "can zoom out below the starting view");
  assert.ok(max >= start.scale * 8 - 1e-9);
  const out = zoomAt(start, 0.001, { x: 640, y: 360 }, screen, image);
  near(out.scale, min);
  let v = start;
  for (let i = 0; i < 50; i++)
    v = zoomAt(v, 2, { x: 640, y: 360 }, screen, image);
  near(v.scale, max);
});

test("on a portrait screen the starting view is already the smallest zoom", () => {
  const { min } = scaleLimits(portrait, image);
  near(min, fillWidthView(portrait, image).scale);
});

test("small images still get a useful zoom range", () => {
  // 31 px image: the starting view is already 41 screen px per pixel; max must be >= 8x that.
  const small = { width: 31, height: 31 };
  const { max } = scaleLimits(screen, small);
  assert.ok(max / fillWidthView(screen, small).scale >= 8 - 1e-9);
});

test("panning cannot push more than 75% of the image off screen", () => {
  const start = zoomAt(
    fillWidthView(screen, image),
    4,
    { x: 640, y: 360 },
    screen,
    image,
  );
  const far = panBy(start, -1e6, 1e6, screen, image);
  const w = image.width * far.scale;
  const h = image.height * far.scale;
  assert.ok(far.tx + w >= 0.25 * w - 1e-6);
  assert.ok(far.ty <= screen.height - 0.25 * h + 1e-6);
  // A small pan inside the allowed range is applied exactly.
  const small = panBy(start, 10, -5, screen, image);
  near(small.tx, start.tx + 10);
  near(small.ty, start.ty - 5);
});

test("the cropped top and bottom of a fill-width view can be reached by panning", () => {
  const start = fillWidthView(screen, image);
  const down = panBy(start, 0, 600, screen, image);
  near(down.ty, start.ty + 600);
  // The image top edge is now on screen.
  assert.ok(imageToScreen(down, { x: 0, y: 0 }).y > 0);
});

test("screen/image conversions are inverses", () => {
  const v = { scale: 12.5, tx: -40, ty: 33 };
  const p = { x: 321.5, y: 99.25 };
  const back = imageToScreen(v, screenToImage(v, p));
  near(back.x, p.x);
  near(back.y, p.y);
});

test("clampView repairs an out-of-range scale", () => {
  const v = clampView({ scale: 1e6, tx: 0, ty: 0 }, screen, image);
  near(v.scale, scaleLimits(screen, image).max);
});

test("wheel factor: scrolling up zooms in, down zooms out, pinch is stronger", () => {
  assert.ok(wheelFactor(-100, 0, false) > 1);
  assert.ok(wheelFactor(100, 0, false) < 1);
  near(wheelFactor(-100, 0, false) * wheelFactor(100, 0, false), 1);
  assert.ok(wheelFactor(-5, 0, true) > wheelFactor(-5, 0, false));
  // Line-based wheels (Firefox) must not feel 16x weaker than pixel-based ones.
  near(wheelFactor(-3, 1, false), wheelFactor(-48, 0, false));
});

test("with a focus, the starting view fills the width with the focus, not the whole image", () => {
  const world = { width: 147, height: 147, focus: { width: 59, height: 59 } };
  const v = fillWidthView(screen, world);
  near(v.scale, 1280 / 59);
  // The focus (centred in the world) spans exactly the screen width...
  const left = imageToScreen(v, { x: (147 - 59) / 2, y: 0 });
  const right = imageToScreen(v, { x: (147 + 59) / 2, y: 0 });
  near(left.x, 0, 1e-6);
  near(right.x, 1280, 1e-6);
  // ...and the world centre stays at the screen centre.
  const c = imageToScreen(v, { x: 73.5, y: 73.5 });
  near(c.x, 640, 1e-6);
  near(c.y, 360, 1e-6);
});

test("with a focus, zoom-out reaches the whole world and zoom-in is relative to the focus", () => {
  const world = { width: 147, height: 147, focus: { width: 59, height: 59 } };
  const { min, max } = scaleLimits(screen, world);
  near(min, containView(screen, world).scale);
  assert.ok(min < fillWidthView(screen, world).scale);
  assert.ok(max >= fillWidthView(screen, world).scale * 8 - 1e-9);
});
