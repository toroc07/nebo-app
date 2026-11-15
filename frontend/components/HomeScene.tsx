"use client";
import { useEffect, useRef, useState, type CSSProperties, type Ref } from "react";
import { ArrowLeft, BookOpen, Rocket, Users } from "lucide-react";
import TutorialTour from "./TutorialTour";
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

/*
 * Crew roster. Short professional profiles, kept to a title (no invented bios or credentials).
 */
const CREW = [
  {
    name: "Jasen Mihovil Yukopila Escobar",
    role: "Frontend Developer",
    photo: "/crew/jasen.webp",
    github: "Jmyukopila",
  },
  {
    name: "Alejandro Patron Montero",
    role: "Fullstack Developer & Data",
    photo: "/crew/alejandro.webp",
    github: "pxtroniwnl",
  },
  {
    name: "Carlos Miguel Toro Torres",
    role: "Fullstack Developer & Data",
    photo: "/crew/carlos.webp",
    github: "toroc07",
  },
  {
    name: "Shalom Jhoanna Arrieta Marrugo",
    role: "Backend Developer & Data",
    photo: "/crew/shalom.webp",
    github: "shalom-A26",
  },
  {
    name: "Dariem Antonio Garcia Cardona",
    role: "Data Engineer & Scientist",
    photo: "/crew/daryem.webp",
    github: "Dmgar",
  },
  {
    name: "Katlyn Gutierrez Cardona",
    role: "Storyteller & Communications",
    photo: "/crew/katlyn.webp",
  },
];

export default function HomeScene({
  headingRef,
  onStart,
}: {
  headingRef?: Ref<HTMLHeadingElement>;
  onStart: () => void;
}) {
  const [off, setOff] = useState(false);
  const [touring, setTouring] = useState(false);
  const [showCrew, setShowCrew] = useState(false);
  const tutorialButton = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);
  // Back on TUTORIAL after closing the tour (TutorialTour focuses its own step titles).
  useEffect(() => {
    if (touring) opened.current = true;
    else if (opened.current) tutorialButton.current?.focus();
  }, [touring]);
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
        {showCrew ? null : (
          <img
            className={s.logo}
            src="/brand/nebo-logo-ui.png"
            alt=""
            aria-hidden="true"
            width={504}
            height={393}
            draggable={false}
          />
        )}
        {showCrew ? (
          <section className={s.crew} aria-labelledby="crew-title">
            <header className={s.crewHead}>
              <h2 id="crew-title">Crew</h2>
              <button type="button" className={s.crewBack} onClick={() => setShowCrew(false)} autoFocus>
                <ArrowLeft aria-hidden="true" /> Back
              </button>
            </header>
            <p className={s.crewNote}>Data Science students · Universidad Tecnológica de Bolívar</p>
            <ul className={s.crewList}>
              {CREW.map((m) => {
                const card = (
                  <>
                    <img src={m.photo} alt="" width={96} height={96} draggable={false} />
                    <strong>{m.name}</strong>
                    <span>{m.role}</span>
                    {m.github ? <span className={s.handle}>@{m.github} ↗</span> : null}
                  </>
                );
                return (
                  <li key={m.name}>
                    {m.github ? (
                      <a
                        className={s.member}
                        href={`https://github.com/${m.github}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`${m.name} on GitHub (opens in a new tab)`}
                      >
                        {card}
                      </a>
                    ) : (
                      <div className={s.member}>{card}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : (
          <>
        <header className={s.header}>
          <p className={s.status}>
            <span aria-hidden="true" /> Landed · Earth · systems ready
          </p>
          <h1 id="home-title" ref={headingRef} tabIndex={-1}>
            Nebo
          </h1>
          <p className={s.tagline}>The infrared sky of SPHEREx, epoch by epoch.</p>
        </header>
        <nav className={s.menu} aria-label="Start menu" inert={touring || undefined}>
          <button type="button" className={s.start} onClick={start}>
            <Rocket aria-hidden="true" />
            <span>
              <strong>Start</strong>
              <small>Launch to the sky</small>
            </span>
          </button>
          <button type="button" ref={tutorialButton} className={s.tutorial} onClick={() => setTouring(true)}>
            <BookOpen aria-hidden="true" />
            <span>
              <strong>Tutorial</strong>
              <small>Every section, step by step</small>
            </span>
          </button>
          <button type="button" className={s.tutorial} onClick={() => setShowCrew(true)}>
            <Users aria-hidden="true" />
            <span>
              <strong>Crew</strong>
              <small>The team on board</small>
            </span>
          </button>
        </nav>
          </>
        )}
      </div>
      {touring && (
        <TutorialTour
          onClose={() => setTouring(false)}
          onStart={() => {
            setTouring(false);
            start();
          }}
        />
      )}
    </section>
  );
}
