"use client";
// Sound button (fixed, bottom-left) plus the app-wide click and hover sounds. Controls are not
// wired one by one: a single delegated listener recognises buttons, links, selects and sliders,
// so new screens get their sounds for free.
import { Volume2, VolumeX } from "lucide-react";
import { useEffect, useState } from "react";
import { audio, sfx } from "@/lib/audio";
import s from "./audio.module.css";

// What counts as a control. `data-silent` opts one out (the sound button plays its own cue).
const CONTROL = 'button, a[href], select, [role="button"], [role="tab"], input[type="range"]';

function controlOf(target: EventTarget | null): HTMLElement | null {
  const el = (target as HTMLElement | null)?.closest?.<HTMLElement>(CONTROL) ?? null;
  if (!el || el.closest("[data-silent]") || (el as HTMLButtonElement).disabled) return null;
  return el;
}

export default function AudioControl() {
  // Starts muted on the server and on first paint so hydration matches; the saved choice
  // arrives in the effect below.
  const [muted, setMuted] = useState(true);

  useEffect(() => {
    setMuted(audio.isMuted());
    const off = audio.subscribe(() => setMuted(audio.isMuted()));

    let lastHover: HTMLElement | null = null;
    const down = (e: PointerEvent) => {
      audio.unlock();
      if (controlOf(e.target)) sfx.click();
    };
    const over = (e: PointerEvent) => {
      // Touch has no hover; the "pointerover" it fires right before a tap would double the click.
      if (e.pointerType !== "mouse") return;
      const el = controlOf(e.target);
      if (el && el !== lastHover) sfx.hover();
      lastHover = el;
    };
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("pointerover", over, true);
    return () => {
      off();
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("pointerover", over, true);
    };
  }, []);

  return (
    <button
      type="button"
      data-silent
      className={s.toggle}
      aria-pressed={!muted}
      aria-label={muted ? "Turn sound on" : "Turn sound off"}
      title={muted ? "Sound off" : "Sound on"}
      onClick={() => audio.toggle()}
    >
      {muted ? <VolumeX aria-hidden="true" size={18} /> : <Volume2 aria-hidden="true" size={18} />}
    </button>
  );
}
