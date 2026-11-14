// Pure pan/zoom math for the image viewer. No DOM here so it can be unit tested.
//
// Coordinate systems:
//  - image space: CSS px of the image at scale 1, origin at its top-left corner, so the image
//    spans [0, width] x [0, height] and pixel i covers [i, i + 1] (its centre is i + 0.5).
//  - screen space: CSS px inside the viewer container, origin at its top-left corner.
// A view maps image -> screen as `screen = image * scale + (tx, ty)`.

export type Size = { width: number; height: number };
export type Point = { x: number; y: number };
export type View = { scale: number; tx: number; ty: number };
/**
 * The scrollable area, plus the part of it the starting view should fill the screen width with.
 * The viewer's world is the largest field of view, but it starts on a smaller one (`focus`).
 */
export type Space = Size & { focus?: Size };

/** Highest zoom, in screen px per image px, when the starting view is already very large. */
const MAX_SCREEN_PX_PER_IMAGE_PX = 64;
/** Zooming in is always allowed at least this many times beyond the starting view. */
const MIN_ZOOM_RANGE = 8;
/** At least this fraction of the image must stay on screen when panning. */
const MIN_VISIBLE = 0.25;

/** The whole image visible ("contain"), as large as it can be, centred. The smallest zoom. */
export function containView(container: Size, image: Size): View {
  const scale = Math.min(
    container.width / image.width,
    container.height / image.height,
  );
  return {
    scale,
    tx: (container.width - image.width * scale) / 2,
    ty: (container.height - image.height * scale) / 2,
  };
}

/**
 * The image spans the full width of the screen, centred vertically. On a wide screen a square
 * image is then taller than the screen, so the top and bottom are cropped and reached by
 * panning; this is the starting view because it uses the whole screen instead of leaving bars.
 */
export function fillWidthView(container: Size, image: Space): View {
  const scale = container.width / (image.focus ?? image).width;
  // Centred on the image centre; with no `focus` this is tx = 0, the image spans the screen.
  return {
    scale,
    tx: (container.width - image.width * scale) / 2,
    ty: (container.height - image.height * scale) / 2,
  };
}

export function scaleLimits(
  container: Size,
  image: Space,
): { min: number; max: number } {
  const start = fillWidthView(container, image).scale;
  const whole = containView(container, image).scale;
  return {
    // Zooming out stops at the whole image: smaller than that only adds empty space.
    min: Math.min(whole, start),
    max: Math.max(MAX_SCREEN_PX_PER_IMAGE_PX, start * MIN_ZOOM_RANGE),
  };
}

/** Clamps scale to the allowed range and keeps a part of the image on screen. */
export function clampView(view: View, container: Size, image: Space): View {
  const { min, max } = scaleLimits(container, image);
  const scale = Math.min(max, Math.max(min, view.scale));
  const w = image.width * scale;
  const h = image.height * scale;
  return {
    scale,
    tx: Math.min(
      container.width - MIN_VISIBLE * w,
      Math.max(-(1 - MIN_VISIBLE) * w, view.tx),
    ),
    ty: Math.min(
      container.height - MIN_VISIBLE * h,
      Math.max(-(1 - MIN_VISIBLE) * h, view.ty),
    ),
  };
}

/** Multiplies the scale by `factor` keeping the image point under `anchor` where it is. */
export function zoomAt(
  view: View,
  factor: number,
  anchor: Point,
  container: Size,
  image: Space,
): View {
  const { min, max } = scaleLimits(container, image);
  const scale = Math.min(max, Math.max(min, view.scale * factor));
  const f = scale / view.scale;
  return clampView(
    {
      scale,
      tx: anchor.x - (anchor.x - view.tx) * f,
      ty: anchor.y - (anchor.y - view.ty) * f,
    },
    container,
    image,
  );
}

export function panBy(
  view: View,
  dx: number,
  dy: number,
  container: Size,
  image: Space,
): View {
  return clampView(
    { ...view, tx: view.tx + dx, ty: view.ty + dy },
    container,
    image,
  );
}

export function screenToImage(view: View, p: Point): Point {
  return { x: (p.x - view.tx) / view.scale, y: (p.y - view.ty) / view.scale };
}

export function imageToScreen(view: View, p: Point): Point {
  return { x: p.x * view.scale + view.tx, y: p.y * view.scale + view.ty };
}

/** Wheel `deltaY` -> zoom factor. Trackpad pinch arrives as a `ctrlKey` wheel with small deltas. */
export function wheelFactor(
  deltaY: number,
  deltaMode: number,
  ctrlKey: boolean,
): number {
  // deltaMode 1 = lines; convert to approximate pixels so mouse wheels feel like trackpads.
  const px =
    deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  return Math.exp(-px * (ctrlKey ? 0.01 : 0.0015));
}
