// "Begin exploring" transition: a hyperspace tunnel that doubles as the loading screen.
//
//   launch   the camera tips up and the stars stretch into streaks (speed 0 -> 1)
//   cruise   full speed, as long as the images are still loading
//   arrive   once the viewer has data AND the minimum time has passed: decelerate, then fade out
//
// This file is framework-free: a timeline function (time -> how the scene should look) and a tiny
// controller shared by the menu (which launches) and the overlay (which renders). The overlay
// lives in the root layout, so it survives the route change from the menu to the viewer and the
// animation never restarts or cuts.

export type WarpPhase = "launch" | "cruise" | "arrive" | "done";

export type Timing = {
  /** Seconds until the overlay is fully opaque. */
  fadeIn: number;
  /** Seconds for the speed to ramp from 0 to full. */
  launch: number;
  /** Seconds for the camera to finish tipping up. */
  tilt: number;
  /** The tunnel is never shown for less than this, however fast the data arrives. */
  minTotal: number;
  /** Safety net: after this long the arrival is forced, so a page that never loads cannot trap. */
  maxTotal: number;
  /** Seconds of the arrival: decelerate and fade out. */
  arrive: number;
};

export const MOTION: Timing = {
  fadeIn: 0.35,
  launch: 0.9,
  tilt: 0.8,
  minTotal: 1.9,
  maxTotal: 12,
  arrive: 1.0,
};

/** Reduced motion: no tunnel, just a quick dim-and-reveal. */
export const REDUCED: Timing = {
  fadeIn: 0.15,
  launch: 0.15,
  tilt: 0.15,
  minTotal: 0.4,
  maxTotal: 12,
  arrive: 0.25,
};

/** Where the vanishing point sits once the camera has tipped up (0 = top, 1 = bottom of screen). */
export const LOOK_UP_Y = 0.3;

/** Where "Begin exploring" is taking the user: the sky globe, or the observation viewer. */
export type WarpTarget = "explore" | "viewer";

export type Timeline = {
  /** Where the transition is heading; decides what "ready" means. */
  target: WarpTarget;
  /** Seconds, same clock as `now` below. */
  launchedAt: number;
  /** When the viewer first reported it was ready; null while it is still loading. */
  readyAt: number | null;
};

export type Frame = {
  phase: WarpPhase;
  /** Opacity of the whole overlay, 0..1. */
  opacity: number;
  /** Speed of the flight, 0..1. */
  speed: number;
  /** Vertical position of the vanishing point, 0..1 of the screen height. */
  centerY: number;
  /** Scale of the canvas: it grows slightly while arriving, as if flying through. */
  zoom: number;
  /**
   * Opacity of the "Preparing the images…" text. It is gone well before the viewer shows
   * through, so the text never sits on top of the interface during the crossfade.
   */
  labelOpacity: number;
};

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const easeOut = (x: number) => 1 - (1 - x) * (1 - x);
const easeIn = (x: number) => x * x;
const easeInOut = (x: number) =>
  x < 0.5 ? 2 * x * x : 1 - 2 * (1 - x) * (1 - x);

/** When the arrival begins, in seconds after launch. */
export function arriveStart(tl: Timeline, timing: Timing): number {
  const ready = tl.readyAt === null ? Infinity : tl.readyAt - tl.launchedAt;
  return Math.min(Math.max(timing.minTotal, ready), timing.maxTotal);
}

/** How the scene looks `now`. Pure: the same input always gives the same frame. */
export function frameAt(tl: Timeline, now: number, timing: Timing): Frame {
  const t = Math.max(0, now - tl.launchedAt);
  const start = arriveStart(tl, timing);

  if (t < start) {
    return {
      phase: t < timing.launch ? "launch" : "cruise",
      opacity: easeOut(clamp01(t / timing.fadeIn)),
      speed: easeIn(clamp01(t / timing.launch)),
      centerY: 0.5 + (LOOK_UP_Y - 0.5) * easeInOut(clamp01(t / timing.tilt)),
      zoom: 1,
      // Appears once the tunnel is already moving, not on a blank screen.
      labelOpacity: easeOut(clamp01((t - 0.2) / 0.4)),
    };
  }

  const a = clamp01((t - start) / timing.arrive);
  if (a >= 1) {
    return {
      phase: "done",
      opacity: 0,
      speed: 0,
      centerY: LOOK_UP_Y,
      zoom: 1.18,
      labelOpacity: 0,
    };
  }
  // Slow down first, and only fade once the streaks have already shortened: the tunnel settles
  // into stars instead of vanishing mid-flight.
  return {
    phase: "arrive",
    opacity: 1 - easeInOut(clamp01((a - 0.3) / 0.7)),
    speed: (1 - easeOut(a)) * (1 - easeOut(a)),
    centerY: LOOK_UP_Y,
    zoom: 1 + 0.18 * easeOut(a),
    labelOpacity: 1 - clamp01(a / 0.25),
  };
}

// --- viewer readiness ------------------------------------------------------------------------

type Queryable = {
  querySelector(selector: string): {
    complete?: boolean;
    naturalWidth?: number;
    textContent: string | null;
  } | null;
};

/**
 * Whether the observation viewer has something to show: an epoch image has loaded, or it has
 * given up and shows an error. It reads the page instead of being told, so the viewer's code
 * does not depend on the transition (and nothing breaks if the viewer is redesigned: the
 * safety net in `Timing.maxTotal` covers a selector that stops matching).
 */
export function isViewerReady(doc: Queryable, pathname: string): boolean {
  if (!pathname.startsWith("/lab/observation")) return false;
  const image = doc.querySelector('[role="application"] img');
  if (image && image.complete && (image.naturalWidth ?? 0) > 0) return true;
  // The empty `role="alert"` element Next.js adds for route announcements is not an error.
  const alert = doc.querySelector('main [role="alert"]');
  return !!alert && (alert.textContent ?? "").trim().length > 0;
}

/**
 * Whether the sky globe has something to show: the map (Aladin) has mounted in the visible
 * explorer and is no longer loading, or it failed and offers a retry (which is also "ready": the
 * user must see the error, not a tunnel). While the map's code is still being downloaded there is
 * no `.aladin-host` yet, so that is "not ready" too.
 */
export function isExploreReady(doc: Queryable): boolean {
  const open = ".explorer-grid:not([hidden])";
  if (!doc.querySelector(`${open} .aladin-host`)) return false;
  if (doc.querySelector(`${open} .sky-message button`)) return true;
  return doc.querySelector(`${open} .sky-message`) === null;
}

/** Ready or not for the destination the transition is heading to. */
export function isDestinationReady(
  target: WarpTarget,
  doc: Queryable,
  pathname: string,
): boolean {
  return target === "explore"
    ? isExploreReady(doc)
    : isViewerReady(doc, pathname);
}

/** The destination's own loading message ("Loading…", "Building: downloading 3/24"), if it shows one. */
export function viewerStatus(doc: Queryable): string {
  return (doc.querySelector('main [role="status"]')?.textContent ?? "").trim();
}

// --- controller ------------------------------------------------------------------------------

type Listener = () => void;

/** Shared state between whoever launches the transition and the overlay that draws it. */
export class WarpController {
  private tl: Timeline | null = null;
  private listeners = new Set<Listener>();

  /** Starts the transition. Ignored while one is already running. */
  launch(now: number, target: WarpTarget): void {
    if (this.tl) return;
    this.tl = { target, launchedAt: now, readyAt: null };
    this.emit();
  }

  /** The destination has data to show. Only the first call counts. */
  markReady(now: number): void {
    if (this.tl && this.tl.readyAt === null)
      this.tl = { ...this.tl, readyAt: now };
  }

  /** The animation has played out. */
  finish(): void {
    if (!this.tl) return;
    this.tl = null;
    this.emit();
  }

  timeline(): Timeline | null {
    return this.tl;
  }

  isActive(): boolean {
    return this.tl !== null;
  }

  isReady(): boolean {
    return this.tl !== null && this.tl.readyAt !== null;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    this.listeners.forEach((l) => l());
  }
}

/** The one controller of the app. It is module state, which client-side navigation preserves. */
export const warp = new WarpController();

/** Starts the transition now. Safe to call on the server: it does nothing there. */
export function launchWarp(target: WarpTarget): void {
  if (typeof performance !== "undefined") {
    warp.launch(performance.now() / 1000, target);
  }
}
