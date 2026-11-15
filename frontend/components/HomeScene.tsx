"use client";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type Ref } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Compass, Orbit, Rocket, ScanEye } from "lucide-react";
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
/** Bounding box of the forest window's glass (art pixels); the octagon is a clip-path. */
export const HOME_WINDOW = { x: 95, y: 250, w: 270, h: 350 };

const bayStyle = {
  "--art-w": HOME_ART.w,
  "--art-h": HOME_ART.h,
  "--bay-x": HOME_BAY.x,
  "--bay-y": HOME_BAY.y,
  "--bay-w": HOME_BAY.w,
  "--bay-h": HOME_BAY.h,
  "--win-x": HOME_WINDOW.x,
  "--win-y": HOME_WINDOW.y,
  "--win-w": HOME_WINDOW.w,
  "--win-h": HOME_WINDOW.h,
} as CSSProperties;

/*
 * Life outside the window: leaves drifting down and dust motes in the sunlight. Fixed values
 * (no Math.random) so server and client render the same markup.
 * [left %, delay s, duration s, size art-px, sway art-px, hue]
 */
const LEAVES: [number, number, number, number, number, string][] = [
  [8, 0, 9, 16, 34, "#e8a33a"],
  [22, 3.2, 11, 13, -28, "#c9662a"],
  [37, 6.5, 10, 18, 40, "#d9b44a"],
  [51, 1.6, 12, 14, -36, "#9fae3c"],
  [64, 4.8, 9.5, 16, 30, "#e08a2e"],
  [78, 8.1, 11.5, 12, -24, "#c9662a"],
  [90, 2.4, 10.5, 15, -40, "#e8a33a"],
  [30, 9.6, 12.5, 11, 26, "#b8c24a"],
  [45, 0.8, 8.5, 13, -30, "#d97a2a"],
  [70, 5.6, 10, 17, 36, "#c9a03a"],
  [15, 7.2, 11, 12, -22, "#9fae3c"],
  [58, 10.4, 9, 14, 28, "#e8a33a"],
];
/** The tutorial, shown on the same wall screen as the menu. */
const STEPS = [
  {
    icon: Rocket,
    title: "Launch",
    text: "Press START: the ship lifts off and you take the cockpit, flying over the SPHEREx all-sky map.",
  },
  {
    icon: Compass,
    title: "Fly",
    text: "Drag the sky to move and zoom from the console. Pick a featured object in Objects, or type a position in Coords.",
  },
  {
    icon: ScanEye,
    title: "Observe",
    text: "Press View images. Nebo fetches the real SPHEREx images of that field from NASA/IPAC IRSA, one per epoch. A new field can take a minute.",
  },
  {
    icon: Orbit,
    title: "Compare",
    text: "Play the blink or step through the epochs with the same detector. What moves is an observed change, a candidate signal, never a confirmed discovery.",
  },
];

/** [left %, top %, delay s, duration s] */
const MOTES: [number, number, number, number][] = [
  [12, 30, 0, 7],
  [20, 18, 2.5, 9],
  [28, 42, 1.2, 8],
  [16, 55, 4, 10],
  [34, 26, 5.5, 7.5],
  [42, 48, 3, 9.5],
  [8, 40, 6.2, 8.5],
];

export default function HomeScene({
  headingRef,
  onStart,
}: {
  headingRef?: Ref<HTMLHeadingElement>;
  onStart: () => void;
}) {
  const [off, setOff] = useState(false);
  const [mode, setMode] = useState<"menu" | "tutorial">("menu");
  const [step, setStep] = useState(0);
  const stepTitle = useRef<HTMLHeadingElement>(null);
  const tutorialButton = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);
  // Keyboard and screen-reader users land on each new step title, and back on TUTORIAL after.
  useEffect(() => {
    if (mode === "tutorial") {
      opened.current = true;
      stepTitle.current?.focus();
    } else if (opened.current) {
      tutorialButton.current?.focus();
    }
  }, [mode, step]);
  const last = step === STEPS.length - 1;
  const next = () => (last ? start() : setStep((n) => n + 1));
  const previous = () => (step === 0 ? setMode("menu") : setStep((n) => n - 1));
  function onTourKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowRight") next();
    else if (event.key === "ArrowLeft") previous();
    else if (event.key === "Escape") setMode("menu");
    else return;
    event.preventDefault();
  }
  const Icon = STEPS[step].icon;
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
      <div className={s.window} aria-hidden="true">
        {MOTES.map(([left, top, delay, dur], i) => (
          <span
            key={`m${i}`}
            className={s.mote}
            style={{ left: `${left}%`, top: `${top}%`, animationDelay: `${delay}s`, animationDuration: `${dur}s` }}
          />
        ))}
        {LEAVES.map(([left, delay, dur, size, sway, color], i) => (
          <span
            key={`l${i}`}
            className={s.leaf}
            style={
              {
                left: `${left}%`,
                animationDelay: `${delay}s`,
                animationDuration: `${dur}s`,
                "--size": size,
                "--sway": sway,
                "--leaf": color,
              } as CSSProperties
            }
          />
        ))}
      </div>
      <div className={s.screen} data-off={off || undefined}>
        <img
          className={s.logo}
          src="/brand/nebo-logo-ui.png"
          alt=""
          aria-hidden="true"
          width={504}
          height={393}
          draggable={false}
        />
        <header className={s.header} hidden={mode === "tutorial" || undefined}>
          <p className={s.status}>
            <span aria-hidden="true" /> Landed · Earth · systems ready
          </p>
          <h1 id="home-title" ref={headingRef} tabIndex={-1}>
            Nebo
          </h1>
          <p className={s.tagline}>The infrared sky of SPHEREx, epoch by epoch.</p>
        </header>
        {mode === "menu" ? (
          <nav key="menu" className={`${s.menu} ${s.swap}`} aria-label="Start menu">
            <button type="button" className={s.start} onClick={start}>
              <Rocket aria-hidden="true" />
              <span>
                <strong>Start</strong>
                <small>Launch to the sky</small>
              </span>
            </button>
            <button
              type="button"
              ref={tutorialButton}
              className={s.tutorial}
              onClick={() => {
                setStep(0);
                setMode("tutorial");
              }}
            >
              <BookOpen aria-hidden="true" />
              <span>
                <strong>Tutorial</strong>
                <small>Your first trip, step by step</small>
              </span>
            </button>
          </nav>
        ) : (
          <div key={`step${step}`} className={`${s.tour} ${s.swap}`} onKeyDown={onTourKey}>
            <p className={`${s.status} ${s.tourStatus}`}>
              <span aria-hidden="true" /> Tutorial · step {String(step + 1).padStart(2, "0")} /{" "}
              {String(STEPS.length).padStart(2, "0")}
            </p>
            <ol className={s.progress} aria-hidden="true">
              {STEPS.map((item, i) => (
                <li key={item.title} data-on={i <= step || undefined} />
              ))}
            </ol>
            <div className={s.tourBody} aria-live="polite">
              <div className={s.ring} aria-hidden="true">
                <Icon />
              </div>
              <div>
                <h2 ref={stepTitle} tabIndex={-1}>
                  {STEPS[step].title}
                </h2>
                <p>{STEPS[step].text}</p>
              </div>
            </div>
            <div className={s.tourNav}>
              <button type="button" className={s.back} onClick={previous}>
                <ArrowLeft aria-hidden="true" /> {step === 0 ? "Menu" : "Back"}
              </button>
              <button type="button" className={s.next} onClick={next}>
                {last ? "Launch" : "Next"} <ArrowRight aria-hidden="true" />
              </button>
              <button type="button" className={s.skipTour} onClick={start}>
                Skip tutorial
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
