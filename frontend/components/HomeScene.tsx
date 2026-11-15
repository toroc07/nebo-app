"use client";
import { useState, type CSSProperties, type Ref } from "react";
import { BookOpen, Rocket } from "lucide-react";
import s from "./home.module.css";

/*
 * Start screen: inside the ship, still landed on Earth. The art (home-bg.webp) shows the left
 * side of the command post: a small window onto a forest and mountains, and a switched-off wall
 * screen. The live menu is drawn inside that screen, so it is placed in art pixels and the art is
 * always cover-fitted to the viewport.
 */
export const HOME_ART = { w: 1536, h: 1024 };
/** The screen bay inside home-bg.webp (art pixels). */
export const HOME_BAY = { x: 731, y: 251, w: 701, h: 349 };

const bayStyle = {
  "--art-w": HOME_ART.w,
  "--art-h": HOME_ART.h,
  "--bay-x": HOME_BAY.x,
  "--bay-y": HOME_BAY.y,
  "--bay-w": HOME_BAY.w,
  "--bay-h": HOME_BAY.h,
} as CSSProperties;

export default function HomeScene({
  headingRef,
  onStart,
  onTutorial,
}: {
  headingRef?: Ref<HTMLHeadingElement>;
  onStart: () => void;
  onTutorial: () => void;
}) {
  const [off, setOff] = useState(false);
  /** START: the wall screen switches off first, then the camera turns to the cockpit. */
  function start() {
    if (off) return;
    const reduced =
      document.documentElement.dataset.reduced === "true" ||
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return onStart();
    setOff(true);
    // Matches the 300 ms CRT switch-off in home.module.css.
    window.setTimeout(onStart, 320);
  }
  return (
    <section className={s.scene} data-scene="home" aria-labelledby="home-title" style={bayStyle}>
      <img className={s.room} src="/panels/home-bg.webp" alt="" aria-hidden="true" draggable={false} />
      <div className={s.screen} data-off={off || undefined}>
        <header className={s.header}>
          <p className={s.status}>
            <span aria-hidden="true" /> Landed · Earth · systems ready
          </p>
          <h1 id="home-title" ref={headingRef} tabIndex={-1}>
            <img className={s.logo} src="/brand/nebo-logo.png" alt="Nebo" width={827} height={524} />
          </h1>
          <p className={s.tagline}>The infrared sky of SPHEREx, epoch by epoch.</p>
        </header>
        <nav className={s.menu} aria-label="Start menu">
          <button type="button" className={s.start} onClick={start}>
            <Rocket aria-hidden="true" />
            <span>
              <strong>Start</strong>
              <small>Launch to the sky</small>
            </span>
          </button>
          <button type="button" className={s.tutorial} onClick={onTutorial}>
            <BookOpen aria-hidden="true" />
            <span>
              <strong>Tutorial</strong>
              <small>Your first trip, step by step</small>
            </span>
          </button>
        </nav>
      </div>
    </section>
  );
}
