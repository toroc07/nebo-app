"use client";
// Interactive image surface: fills its parent, zooms (wheel, pinch, buttons, keys), pans by
// dragging, and lets the user drop a pin that reports sky coordinates and can be dragged.
//
// The observation comes at three sizes that are central crops of each other (lib/lab/fov.ts).
// This surface works in the space of the LARGEST one (the "world") and shows only the smallest
// level that covers what is on screen, so zooming in/out switches between 3', 6' and 15' images
// on its own. The image of a level is placed at the centre of the world; the stage never moves
// when the level changes, so the swap is invisible apart from the sky it adds or removes.
//
// All math lives in lib/lab/{viewport,sky,fov}.ts (unit tested); this file only translates
// pointer/keyboard events into those calls.
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import {
  clampView,
  containView,
  fillWidthView,
  imageToScreen,
  panBy,
  screenToImage,
  wheelFactor,
  zoomAt,
  type Point,
  type Size,
  type Space,
  type View,
} from "@/lib/lab/viewport";
import {
  chooseLevel,
  fieldOfViewArcmin,
  levelOffset,
  visibleWorldRect,
  type Level,
  type SizeName,
} from "@/lib/lab/fov";
import {
  pixelToSky,
  skyToPixel,
  type PixelPoint,
  type SkyGrid,
  type SkyPoint,
} from "@/lib/lab/sky";
import s from "./lab.module.css";

/** `px` is the pixel index in the image of the level being shown. */
export type Hover = { sky: SkyPoint; px: PixelPoint } | null;

type Props = {
  /** URL of the current epoch at the current level. */
  src: string;
  alt: string;
  /** Sky grid of the world, i.e. of the largest level. */
  grid: SkyGrid;
  levels: Level[];
  levelName: SizeName;
  /** The level whose width the starting view fills the screen with. */
  startLevel: SizeName;
  onLevelChange: (name: SizeName) => void;
  /** Changing it refits the view (new object or detector). The epoch must not change it. */
  resetKey: string;
  /** Catalog position as a 0-based pixel index in the current level, or null. */
  marker: PixelPoint | null;
  pin: SkyPoint | null;
  /** `final` is false while the pin is being dragged and true once the position is settled. */
  onPinChange: (pin: SkyPoint | null, final: boolean) => void;
  onHover: (hover: Hover) => void;
  onImageError: () => void;
  /** Pressing C on the image switches between the infrared band and colour. */
  onToggleDisplay?: () => void;
};

// A press that moves less than this is a click (drops a pin), not a pan.
const DRAG_THRESHOLD_PX = 4;
const KEY_PAN_PX = 40;
const BUTTON_ZOOM = 1.5;

const dist = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
const mid = (a: Point, b: Point): Point => ({
  x: (a.x + b.x) / 2,
  y: (a.y + b.y) / 2,
});

export default function ImageViewport({
  src,
  alt,
  grid,
  levels,
  levelName,
  startLevel,
  onLevelChange,
  resetKey,
  marker,
  pin,
  onPinChange,
  onHover,
  onImageError,
  onToggleDisplay,
}: Props) {
  const surface = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<Size>({ width: 0, height: 0 });
  const [view, setView] = useState<View | null>(null);

  const world: Size = useMemo(
    () => ({ width: grid.width, height: grid.height }),
    [grid.width, grid.height],
  );
  const level = levels.find((l) => l.name === levelName) ?? levels.at(-1)!;
  const focus = levels.find((l) => l.name === startLevel) ?? levels[0] ?? world;
  const space: Space = useMemo(
    () => ({
      ...world,
      focus: { width: focus.width, height: focus.height },
    }),
    [world, focus.width, focus.height],
  );
  // Top-left of the current level's image inside the world, in world pixels.
  const offset = useMemo(() => levelOffset(world, level), [world, level]);

  // Latest values for native listeners and rAF callbacks, which would otherwise see stale state.
  const boxRef = useRef(box);
  const spaceRef = useRef(space);
  const viewRef = useRef(view);
  const gridRef = useRef(grid);
  const levelRef = useRef({ level, offset });
  boxRef.current = box;
  spaceRef.current = space;
  viewRef.current = view;
  gridRef.current = grid;
  levelRef.current = { level, offset };

  // False while the view is the automatic fit, so a window resize can refit it; true once the
  // user has zoomed or panned, so a resize only clamps it instead of throwing their view away.
  const touched = useRef(false);
  const lastKey = useRef("");

  useEffect(() => {
    const el = surface.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setBox({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // The box this view was last laid out for, to keep the centre of the screen on the same point
  // of the image when the window is resized.
  const lastBox = useRef<Size>({ width: 0, height: 0 });

  useEffect(() => {
    if (!box.width || !box.height) return;
    const previous = lastBox.current;
    lastBox.current = box;
    const key = `${resetKey}|${space.width}x${space.height}|${space.focus?.width}`;
    if (key !== lastKey.current) {
      lastKey.current = key;
      touched.current = false;
      setView(fillWidthView(box, space));
      return;
    }
    setView((v) => {
      if (!v || !touched.current) return fillWidthView(box, space);
      // Resizing grows or shrinks the box around its centre, so shift the view by half the
      // change: whatever was at the centre of the screen stays there.
      const dx = previous.width ? (box.width - previous.width) / 2 : 0;
      const dy = previous.height ? (box.height - previous.height) / 2 : 0;
      return clampView({ ...v, tx: v.tx + dx, ty: v.ty + dy }, box, space);
    });
  }, [box, space, resetKey]);

  // Zooming picks the level: the smallest image that still covers what is on screen.
  useEffect(() => {
    if (!view || !box.width || levels.length === 0) return;
    // Until the user zooms or pans, the view is the automatic fit, so the level comes from that
    // fit computed for the current box, not from `view`, and without the hysteresis. When the
    // window is resized, `view` is still the old one while `box` is already the new one in this
    // render; using it would look like "more sky than the level covers", jump to a larger level
    // and the hysteresis would then refuse to leave it.
    // On a wide screen the fit is served by the start level; on a tall one (a phone) it shows
    // more sky vertically than the start level has, so a larger level is the right one from the
    // start instead of leaving empty bars that a first zoom would suddenly fill.
    const auto = !touched.current;
    const basis = auto ? fillWidthView(box, space) : view;
    const next = chooseLevel(
      levels,
      world,
      visibleWorldRect(basis, box, world),
      auto ? null : levelName,
    );
    if (next !== levelName) onLevelChange(next);
  }, [view, box, levels, levelName, space, world, onLevelChange]);

  // Wheel must be a non-passive native listener: React's onWheel is passive and cannot stop the
  // page from scrolling.
  useEffect(() => {
    const el = surface.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const anchor = { x: e.clientX - r.left, y: e.clientY - r.top };
      touched.current = true;
      setView(
        (v) =>
          v &&
          zoomAt(
            v,
            wheelFactor(e.deltaY, e.deltaMode, e.ctrlKey),
            anchor,
            boxRef.current,
            spaceRef.current,
          ),
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  function local(e: { clientX: number; clientY: number }): Point {
    const r = surface.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  /** The current level's image as a rectangle in image space (pixel i covers [i, i + 1]). */
  function levelRect() {
    const { level: l, offset: o } = levelRef.current;
    return { x0: o.x, y0: o.y, x1: o.x + l.width, y1: o.y + l.height };
  }

  /** Sky position and level pixel under a screen point, or null if it is off the image. */
  function sampleAt(v: View, p: Point): Hover {
    const ip = screenToImage(v, p);
    const r = levelRect();
    if (ip.x < r.x0 || ip.y < r.y0 || ip.x > r.x1 || ip.y > r.y1) return null;
    // Image space puts pixel i at [i, i + 1]; the sky grid indexes pixel centres, hence -0.5.
    const world = { x: ip.x - 0.5, y: ip.y - 0.5 };
    const o = levelRef.current.offset;
    return {
      sky: pixelToSky(gridRef.current, world.x, world.y),
      px: { x: world.x - o.x, y: world.y - o.y },
    };
  }

  // --- pointer gestures ---------------------------------------------------------------------
  const pointers = useRef(new Map<number, Point>());
  const gesture = useRef({
    start: { x: 0, y: 0 },
    moved: false,
    lastDist: 0,
    lastMid: { x: 0, y: 0 },
  });
  const pinDrag = useRef(false);
  const hoverAt = useRef<Point | null>(null);
  const frame = useRef(0);

  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  function scheduleHover(p: Point | null) {
    hoverAt.current = p;
    if (frame.current) return;
    // One readout update per frame is plenty and keeps dragging smooth.
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const at = hoverAt.current;
      const v = viewRef.current;
      onHover(at && v ? sampleAt(v, at) : null);
    });
  }

  function startPinch() {
    const [a, b] = [...pointers.current.values()];
    gesture.current = {
      start: a,
      moved: true,
      lastDist: dist(a, b),
      lastMid: mid(a, b),
    };
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    surface.current!.setPointerCapture(e.pointerId);
    const p = local(e);
    pointers.current.set(e.pointerId, p);
    if (pointers.current.size === 1) {
      gesture.current = { start: p, moved: false, lastDist: 0, lastMid: p };
    } else if (pointers.current.size === 2) {
      startPinch();
    }
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const p = local(e);
    if (e.pointerType === "mouse") scheduleHover(p);
    const previous = pointers.current.get(e.pointerId);
    if (!previous) return;
    pointers.current.set(e.pointerId, p);
    const g = gesture.current;
    if (pointers.current.size === 1) {
      if (!g.moved && dist(p, g.start) < DRAG_THRESHOLD_PX) return;
      g.moved = true;
      touched.current = true;
      const dx = p.x - previous.x;
      const dy = p.y - previous.y;
      setView((v) => v && panBy(v, dx, dy, boxRef.current, spaceRef.current));
    } else if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const d = dist(a, b);
      const m = mid(a, b);
      const factor = g.lastDist > 0 ? d / g.lastDist : 1;
      const dx = m.x - g.lastMid.x;
      const dy = m.y - g.lastMid.y;
      g.lastDist = d;
      g.lastMid = m;
      touched.current = true;
      setView(
        (v) =>
          v &&
          panBy(
            zoomAt(v, factor, m, boxRef.current, spaceRef.current),
            dx,
            dy,
            boxRef.current,
            spaceRef.current,
          ),
      );
    }
  }

  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    const p = local(e);
    const wasSingle = pointers.current.size === 1;
    pointers.current.delete(e.pointerId);
    if (wasSingle && !gesture.current.moved && e.type === "pointerup") {
      const v = viewRef.current;
      const hit = v && sampleAt(v, p);
      if (hit) onPinChange(hit.sky, true);
    }
    if (pointers.current.size === 1) {
      // One finger of a pinch was lifted: continue as a pan without a jump or a stray click.
      const [rest] = [...pointers.current.values()];
      gesture.current = {
        start: rest,
        moved: true,
        lastDist: 0,
        lastMid: rest,
      };
    }
  }

  function onPointerLeave() {
    if (pointers.current.size === 0) scheduleHover(null);
  }

  function zoomBy(factor: number, anchor?: Point) {
    touched.current = true;
    const b = boxRef.current;
    const a = anchor ?? { x: b.width / 2, y: b.height / 2 };
    setView((v) => v && zoomAt(v, factor, a, b, spaceRef.current));
  }

  /** Back to the starting view: the starting level spans the full width of the screen. */
  function refit() {
    touched.current = false;
    setView(fillWidthView(boxRef.current, spaceRef.current));
  }

  /** The whole world on screen, as large as it fits (the widest zoom-out). */
  function showWhole() {
    touched.current = true;
    setView(containView(boxRef.current, spaceRef.current));
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.target !== e.currentTarget) return;
    const step = e.shiftKey ? KEY_PAN_PX * 4 : KEY_PAN_PX;
    const pan = (dx: number, dy: number) => {
      touched.current = true;
      setView((v) => v && panBy(v, dx, dy, boxRef.current, spaceRef.current));
    };
    switch (e.key) {
      case "+":
      case "=":
        zoomBy(BUTTON_ZOOM);
        break;
      case "-":
      case "_":
        zoomBy(1 / BUTTON_ZOOM);
        break;
      case "0":
        refit();
        break;
      case "9":
        showWhole();
        break;
      case "c":
      case "C":
        if (!onToggleDisplay) return;
        onToggleDisplay();
        break;
      case "ArrowLeft":
        pan(step, 0);
        break;
      case "ArrowRight":
        pan(-step, 0);
        break;
      case "ArrowUp":
        pan(0, step);
        break;
      case "ArrowDown":
        pan(0, -step);
        break;
      case "Enter":
      case " ": {
        // Keyboard users have no pointer: drop the pin at the centre of what they see.
        const v = viewRef.current;
        if (!v) return;
        const c = screenToImage(v, {
          x: boxRef.current.width / 2,
          y: boxRef.current.height / 2,
        });
        const r = levelRect();
        const x = Math.min(r.x1, Math.max(r.x0, c.x));
        const y = Math.min(r.y1, Math.max(r.y0, c.y));
        onPinChange(pixelToSky(gridRef.current, x - 0.5, y - 0.5), true);
        break;
      }
      default:
        return;
    }
    e.preventDefault();
  }

  // --- pin ----------------------------------------------------------------------------------
  const pinScreen = useMemo(() => {
    if (!pin || !view) return null;
    const px = skyToPixel(grid, pin.ra, pin.dec);
    const ip = { x: px.x + 0.5, y: px.y + 0.5 };
    // Hidden (not lost) while it is off the current level's image.
    if (
      ip.x < offset.x ||
      ip.y < offset.y ||
      ip.x > offset.x + level.width ||
      ip.y > offset.y + level.height
    )
      return null;
    return imageToScreen(view, ip);
  }, [pin, view, grid, offset, level]);

  function movePinToScreen(p: Point, final: boolean) {
    const v = viewRef.current;
    if (!v) return;
    const ip = screenToImage(v, p);
    const r = levelRect();
    // Dragging past the edge sticks the pin to the border instead of losing it.
    const x = Math.min(r.x1 - 1e-6, Math.max(r.x0, ip.x));
    const y = Math.min(r.y1 - 1e-6, Math.max(r.y0, ip.y));
    onPinChange(pixelToSky(gridRef.current, x - 0.5, y - 0.5), final);
  }

  function onPinKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const n = e.shiftKey ? 5 : 1;
    const delta: Record<string, [number, number]> = {
      ArrowLeft: [-n, 0],
      ArrowRight: [n, 0],
      ArrowUp: [0, -n],
      ArrowDown: [0, n],
    };
    if (e.key === "Delete" || e.key === "Backspace" || e.key === "Escape") {
      onPinChange(null, true);
      e.preventDefault();
      return;
    }
    const d = delta[e.key];
    if (!d || !pin) return;
    e.preventDefault();
    const cur = skyToPixel(grid, pin.ra, pin.dec);
    const x = Math.min(
      offset.x + level.width - 1,
      Math.max(offset.x, cur.x + d[0]),
    );
    const y = Math.min(
      offset.y + level.height - 1,
      Math.max(offset.y, cur.y + d[1]),
    );
    onPinChange(pixelToSky(grid, x, y), true);
  }

  const startScale =
    box.width && box.height ? fillWidthView(box, space).scale : 1;
  const markerScreen =
    marker && view
      ? imageToScreen(view, {
          x: marker.x + 0.5 + offset.x,
          y: marker.y + 0.5 + offset.y,
        })
      : null;
  const fov =
    view && box.width ? fieldOfViewArcmin(view, box, grid.scaleArcsec) : null;
  const levelArcmin = Math.round((level.width * grid.scaleArcsec) / 60);

  return (
    <div className={s.viewer}>
      <div
        ref={surface}
        className={s.surface}
        tabIndex={0}
        role="application"
        aria-roledescription="image viewer"
        aria-label="SPHEREx image. Scroll or pinch to zoom, drag to pan, click to drop a coordinate pin. Zooming switches automatically between the 3, 6 and 15 arcminute images. Keyboard: plus and minus zoom, arrow keys pan, Enter drops a pin at the centre, 0 fits the width, 9 shows the whole field, C switches between infrared and color."
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
        onDoubleClick={(e) => zoomBy(2, local(e))}
        onKeyDown={onKeyDown}
      >
        {view && (
          <>
            <div
              className={s.checker}
              style={{
                left: view.tx + offset.x * view.scale,
                top: view.ty + offset.y * view.scale,
                width: level.width * view.scale,
                height: level.height * view.scale,
              }}
            />
            <div
              className={s.stage}
              style={{
                width: world.width,
                height: world.height,
                transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})`,
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={src}
                alt={alt}
                className={s.image}
                style={{
                  left: offset.x,
                  top: offset.y,
                  width: level.width,
                  height: level.height,
                }}
                draggable={false}
                onError={onImageError}
              />
            </div>
            {markerScreen && (
              <span
                className={s.marker}
                style={{ left: markerScreen.x, top: markerScreen.y }}
              />
            )}
            {pinScreen && (
              <button
                type="button"
                className={s.pin}
                style={{ left: pinScreen.x, top: pinScreen.y }}
                aria-label="Coordinate pin. Drag it, or use the arrow keys to move it one pixel; Delete removes it."
                onKeyDown={onPinKeyDown}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  e.currentTarget.setPointerCapture(e.pointerId);
                  pinDrag.current = true;
                }}
                onPointerMove={(e) => {
                  if (!pinDrag.current) return;
                  e.stopPropagation();
                  movePinToScreen(local(e), false);
                }}
                onPointerUp={(e) => {
                  if (!pinDrag.current) return;
                  e.stopPropagation();
                  pinDrag.current = false;
                  movePinToScreen(local(e), true);
                }}
                onPointerCancel={() => {
                  pinDrag.current = false;
                }}
              />
            )}
          </>
        )}
      </div>
      <div className={s.zoomControls}>
        <button
          type="button"
          onClick={() => zoomBy(BUTTON_ZOOM)}
          aria-label="Zoom in"
        >
          +
        </button>
        <button
          type="button"
          onClick={() => zoomBy(1 / BUTTON_ZOOM)}
          aria-label="Zoom out"
        >
          −
        </button>
        <button type="button" onClick={refit} title="Fill the screen width (0)">
          Fit
        </button>
        <button
          type="button"
          onClick={showWhole}
          title="Show the whole field (9)"
        >
          Whole
        </button>
        <span className={s.mono} aria-live="off">
          {view ? `${(view.scale / startScale).toFixed(1)}×` : ""}
        </span>
        <span className={s.mono} aria-live="off">
          {fov
            ? `FoV ${fov.width.toFixed(1)}′ × ${fov.height.toFixed(1)}′`
            : ""}
        </span>
        <span className={s.mono} aria-live="off" data-level={levelName}>
          {levelArcmin}′ image
        </span>
      </div>
    </div>
  );
}
