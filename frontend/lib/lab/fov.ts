// Field-of-view levels. The backend serves each observation at three sizes (small 3', medium
// 6', large 15'). They are exact central crops of one image: same centre, same pixel scale, same
// pixels (verified in tests/demo-palettes.test.ts), so they nest like this:
//
//        large  (147 px)  +---------------------+
//        medium ( 59 px)  |      +-------+      |
//        small  ( 31 px)  |      | +---+ |      |
//                         |      | |   | |      |
//
// The viewer treats the LARGEST level as the world and places every smaller level at the centre
// of it. Zooming then just picks the smallest level that still covers what is on screen: zoomed
// in it shows the small crop, zoomed out it loads the larger one. Resolution never changes (all
// levels have the same pixel scale), so the swap only adds or removes sky around the edges.
import type { Point, Size, View } from "./viewport";

export type SizeName = "small" | "medium" | "large";
export const sizeNames: SizeName[] = ["small", "medium", "large"];

export type Level = { name: SizeName; width: number; height: number };
export type Rect = { x0: number; y0: number; x1: number; y1: number };

/**
 * When zooming back in, a smaller level is only taken once the view fits this fraction of it.
 * Without the margin, a view sitting right on a level's edge would flip between two levels on
 * every tiny pan or zoom step.
 */
const SHRINK_MARGIN = 0.9;
/** Tolerance for floating-point error when a view sits exactly on a level's edge. */
const EPS = 1e-6;

/** Top-left corner, in world pixels, of a level centred inside the world. */
export function levelOffset(world: Size, level: Size): Point {
  return {
    x: (world.width - level.width) / 2,
    y: (world.height - level.height) / 2,
  };
}

/** The part of the world that is on screen, in world pixels, clipped to the world. */
export function visibleWorldRect(
  view: View,
  container: Size,
  world: Size,
): Rect {
  return {
    x0: Math.max(0, -view.tx / view.scale),
    y0: Math.max(0, -view.ty / view.scale),
    x1: Math.min(world.width, (container.width - view.tx) / view.scale),
    y1: Math.min(world.height, (container.height - view.ty) / view.scale),
  };
}

/**
 * Which level to show for the visible area: the smallest one that covers it, never changing
 * level for tiny movements. Returns the current level while it still covers the view.
 */
export function chooseLevel(
  levels: Level[],
  world: Size,
  visible: Rect,
  current: SizeName | null,
): SizeName {
  const sorted = [...levels].sort((a, b) => a.width - b.width);
  if (sorted.length === 0)
    throw new Error("chooseLevel needs at least one level");
  const cx = world.width / 2;
  const cy = world.height / 2;
  // `margin` shrinks the level's rectangle around its centre before testing containment.
  const covers = (l: Level, margin: number) =>
    visible.x0 >= cx - (l.width * margin) / 2 - EPS &&
    visible.x1 <= cx + (l.width * margin) / 2 + EPS &&
    visible.y0 >= cy - (l.height * margin) / 2 - EPS &&
    visible.y1 <= cy + (l.height * margin) / 2 + EPS;

  const needed = sorted.find((l) => covers(l, 1)) ?? sorted[sorted.length - 1];
  const now = sorted.find((l) => l.name === current);
  if (!now || !covers(now, 1)) return needed.name;

  // The current level still covers the view: only shrink when a smaller one fits with margin.
  const smaller = sorted.find((l) => covers(l, SHRINK_MARGIN));
  return smaller && smaller.width < now.width ? smaller.name : now.name;
}

/** Sky covered by the whole screen at the current zoom, in arcminutes. */
export function fieldOfViewArcmin(
  view: View,
  container: Size,
  pixelScaleArcsec: number,
): { width: number; height: number } {
  const arcminPerScreenPx = pixelScaleArcsec / 60 / view.scale;
  return {
    width: container.width * arcminPerScreenPx,
    height: container.height * arcminPerScreenPx,
  };
}
