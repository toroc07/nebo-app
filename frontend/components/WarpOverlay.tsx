"use client";
// Full-screen hyperspace tunnel, shown while "Begin exploring" loads the observation viewer. It
// lives in the root layout, so it stays on screen across the route change from the menu to the
// viewer (the animation never restarts), and it takes itself down once the viewer has data.
// The timing is in lib/warp.ts and the star field in lib/warp-render.ts; this file only draws.
import { useEffect, useRef, useState } from "react";
import {
  MOTION,
  REDUCED,
  frameAt,
  isDestinationReady,
  viewerStatus,
  warp,
} from "@/lib/warp";
import {
  STREAK_COUNT,
  TONE_RGB,
  createStreaks,
  mulberry32,
  projectStreak,
  stepStreaks,
} from "@/lib/warp-render";
import s from "./warp.module.css";

// Deep navy, the colour of the dark core and of the trails the streaks leave behind.
const BACKGROUND = "2, 5, 14";

export default function WarpOverlay() {
  const [active, setActive] = useState(false);
  useEffect(() => {
    setActive(warp.isActive());
    return warp.subscribe(() => setActive(warp.isActive()));
  }, []);
  return active ? <Scene /> : null;
}

function Scene() {
  const root = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("");
  // Read once: a preference changed mid-flight is not worth restarting the animation for.
  const [reduced] = useState(
    () =>
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      document.documentElement.dataset.reduced === "true",
  );

  useEffect(() => {
    const el = root.current;
    const cv = canvas.current;
    const label = copy.current;
    const ctx = cv?.getContext("2d");
    if (!el || !cv || !ctx || !label) {
      // No canvas (very old browser): there is nothing to animate, so do not block the page.
      warp.finish();
      return;
    }
    const timing = reduced ? REDUCED : MOTION;
    // Keyboard focus moves here so Enter or Space cannot press the menu button again.
    el.focus({ preventScroll: true });

    const rng = mulberry32(20261114);
    const streaks = createStreaks(STREAK_COUNT, rng);
    let w = 0;
    let h = 0;
    const resize = () => {
      // Capped: the tunnel is soft, and a 4K canvas would cost frames for no visible gain.
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      w = window.innerWidth;
      h = window.innerHeight;
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = `rgb(${BACKGROUND})`;
      ctx.fillRect(0, 0, w, h);
    };
    resize();
    window.addEventListener("resize", resize);

    let raf = 0;
    let last = performance.now() / 1000;
    let nextProbe = 0;
    let shownStatus = "";
    let roll = 0;

    const draw = (speed: number, centerY: number, dt: number) => {
      const cx = w / 2;
      const cy = h * centerY;
      // Each frame only dims the previous one, so fast streaks leave a motion-blur trail.
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = `rgba(${BACKGROUND}, ${0.36 - 0.22 * speed})`;
      ctx.fillRect(0, 0, w, h);

      roll += stepStreaks(streaks, dt, speed, rng);
      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round";
      const thickness = Math.min(1.4, Math.max(0.75, w / 1600));
      for (const star of streaks) {
        const seg = projectStreak(star, speed, roll, w, h, cx, cy);
        if (!seg) continue;
        const [r, g, b] = TONE_RGB[seg.tone];
        ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${seg.alpha})`;
        ctx.lineWidth = seg.width * thickness;
        ctx.beginPath();
        ctx.moveTo(seg.x0, seg.y0);
        ctx.lineTo(seg.x1, seg.y1);
        ctx.stroke();
      }

      // The dark heart of the tunnel, where the stars are still tiny and far away.
      ctx.globalCompositeOperation = "source-over";
      const reach = Math.hypot(w, h);
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, reach * 0.2);
      core.addColorStop(0, `rgba(${BACKGROUND}, 0.92)`);
      core.addColorStop(0.55, `rgba(${BACKGROUND}, 0.45)`);
      core.addColorStop(1, `rgba(${BACKGROUND}, 0)`);
      ctx.fillStyle = core;
      ctx.fillRect(0, 0, w, h);
    };

    const tick = () => {
      const now = performance.now() / 1000;
      const dt = Math.min(0.05, now - last);
      last = now;
      const timeline = warp.timeline();
      if (!timeline) return;

      // Ask the page, ten times a second, whether the viewer has something to show.
      if (!warp.isReady() && now >= nextProbe) {
        nextProbe = now + 0.1;
        if (
          isDestinationReady(
            timeline.target,
            document,
            window.location.pathname,
          )
        )
          warp.markReady(now);
        const text = viewerStatus(document);
        if (text !== shownStatus) {
          shownStatus = text;
          setStatus(text);
        }
      }

      const frame = frameAt(warp.timeline() ?? timeline, now, timing);
      if (frame.phase === "done") {
        warp.finish();
        // Hand the keyboard to where the user has arrived: the viewer's image surface, or else
        // the heading of the screen (focusable, as the menu already does on every change).
        document
          .querySelector<HTMLElement>('[role="application"], main h1')
          ?.focus({ preventScroll: true });
        return;
      }
      el.style.opacity = String(frame.opacity);
      cv.style.transform = `scale(${frame.zoom})`;
      label.style.opacity = String(frame.labelOpacity);
      if (!reduced) draw(frame.speed, frame.centerY, dt);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [reduced]);

  return (
    <div
      ref={root}
      className={s.warp}
      tabIndex={-1}
      data-warp
      data-reduced={reduced}
      style={{ opacity: 0 }}
    >
      <canvas ref={canvas} className={s.canvas} aria-hidden="true" />
      <div ref={copy} className={s.copy} style={{ opacity: 0 }}>
        <p role="status" className={s.label}>
          Preparing the images…
        </p>
        <p className={s.status} aria-hidden="true">
          {status}
        </p>
        <span className={s.bar} aria-hidden="true" />
      </div>
    </div>
  );
}
