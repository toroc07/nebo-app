"use client";
// Power-on of the Nebo app, shown in the cockpit glass after the pan from the start screen and
// before the approach tunnel: a screen line opens, the logo lights up, the system checks scroll
// and a progress bar fills. Pure CSS animation; `onDone` fires when it has played out.
import { useEffect, useRef } from "react";
import { sfx } from "@/lib/audio";
import s from "./neboBoot.module.css";

/** Total length of the power-on, in ms (keep in sync with the CSS timings). */
export const NEBO_BOOT_MS = 3200;

const CHECKS = [
  "NEBO navigation system · v1.0",
  "Link to NASA/IPAC IRSA · SPHEREx",
  "6 detectors · 0.75 to 5.0 microns · calibrated",
  "All-sky map · loaded",
  "Navigation online",
];

export default function NeboBoot({ onDone }: { onDone: () => void }) {
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    const id = window.setTimeout(() => done.current(), NEBO_BOOT_MS);
    // Sounds follow the CSS timings (checks appear at 1150 ms + 260 ms each).
    sfx.powerOn();
    const cues = CHECKS.map((_, i) => window.setTimeout(sfx.tick, 1150 + i * 260));
    cues.push(window.setTimeout(sfx.chime, 1150 + CHECKS.length * 260 + 100));
    return () => {
      window.clearTimeout(id);
      cues.forEach(window.clearTimeout);
    };
  }, []);
  return (
    <div className={s.boot} data-nebo-boot="" role="status" aria-live="polite">
      <span className={s.srOnly}>Starting Nebo…</span>
      <div className={s.line} aria-hidden="true" />
      <div className={s.panel} aria-hidden="true">
        <img
          className={s.logo}
          src="/brand/nebo-logo-ui.png"
          alt=""
          draggable={false}
        />
        <p className={s.word}>NEBO</p>
        <p className={s.tagline}>The infrared sky of SPHEREx</p>
        <ol className={s.checks}>
          {CHECKS.map((text, i) => (
            <li
              key={text}
              style={{ animationDelay: `${1150 + i * 260}ms` }}
              data-last={i === CHECKS.length - 1 ? "" : undefined}
            >
              <span className={s.tick}>›</span> {text}
            </li>
          ))}
        </ol>
        <div className={s.bar}>
          <span />
        </div>
      </div>
    </div>
  );
}
