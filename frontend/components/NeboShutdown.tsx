"use client";
// Power-off of the Nebo app, shown in the cockpit glass when leaving the sky explorer for the
// start menu. It mirrors NeboBoot but plays differently on purpose: the systems go offline one
// by one while rings spin down, then the picture collapses like a CRT (line → dot → black).
// Pure CSS animation; `onDone` fires when it has played out.
import { useEffect, useRef } from "react";
import { sfx } from "@/lib/audio";
import s from "./neboShutdown.module.css";

/** Total length of the power-off, in ms (keep in sync with the CSS timings). */
export const NEBO_SHUTDOWN_MS = 2700;

// Reverse order of the boot checklist: the last system up is the first one down.
const CHECKS = [
  "Navigation · offline",
  "All-sky map · unloaded",
  "6 detectors · standby",
  "Link to NASA/IPAC IRSA · closed",
  "NEBO navigation system · halted",
];
const FIRST_CHECK_MS = 300;
const CHECK_STEP_MS = 220;
const COLLAPSE_MS = 1750;

export default function NeboShutdown({ onDone }: { onDone: () => void }) {
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    const id = window.setTimeout(() => done.current(), NEBO_SHUTDOWN_MS);
    // Sounds follow the CSS timings: one tick per line, then the screen falling silent.
    const cues = CHECKS.map((_, i) => window.setTimeout(sfx.tick, FIRST_CHECK_MS + i * CHECK_STEP_MS));
    cues.push(window.setTimeout(sfx.powerOff, COLLAPSE_MS));
    return () => {
      window.clearTimeout(id);
      cues.forEach(window.clearTimeout);
    };
  }, []);
  return (
    <div className={s.shutdown} data-nebo-shutdown="" role="status" aria-live="polite">
      <span className={s.srOnly}>Shutting down Nebo…</span>
      <div className={s.crt} aria-hidden="true">
        <img className={s.logo} src="/brand/nebo-logo-ui.png" alt="" draggable={false} />
        <p className={s.word}>SYSTEM SHUTDOWN</p>
        {/* Rings that spin down and shrink while the systems go offline (the boot uses a bar). */}
        <svg className={s.rings} viewBox="0 0 100 100" aria-hidden="true">
          <circle className={s.ringOuter} cx="50" cy="50" r="44" />
          <circle className={s.ringMid} cx="50" cy="50" r="32" />
          <circle className={s.ringInner} cx="50" cy="50" r="20" />
          <circle className={s.core} cx="50" cy="50" r="5" />
        </svg>
        <ol className={s.checks}>
          {CHECKS.map((text, i) => (
            <li key={text} style={{ animationDelay: `${FIRST_CHECK_MS + i * CHECK_STEP_MS}ms` }}>
              <span className={s.tick}>›</span> {text}
            </li>
          ))}
        </ol>
      </div>
      <div className={s.dot} aria-hidden="true" />
    </div>
  );
}
