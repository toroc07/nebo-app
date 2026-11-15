"use client";
import { useRef, useState, type CSSProperties } from "react";
import { ArrowRight, Crosshair, LocateFixed, Minus, Plus } from "lucide-react";
import type { Target } from "@/lib/api";
import CoordinatePanel from "./CoordinatePanel";
import s from "./cockpit.module.css";

type Position = { ra: number; dec: number };

/*
 * The cockpit art (public/panels/cockpit.webp) is the bottom of the design
 * reference: 1855 × 378 px, cut at y = 470 of the full 1855 × 848 frame.
 * Live controls sit exactly over the painted ones, so their boxes are written
 * in reference pixels and converted to percentages of the art.
 */
const ART_WIDTH = 1855;
const ART_HEIGHT = 378;
const ART_TOP = 470;

function place(x1: number, y1: number, x2: number, y2: number) {
  const pct = (v: number, of: number) => `${(v / of) * 100}%`;
  return {
    "--l": pct(x1, ART_WIDTH),
    "--t": pct(y1 - ART_TOP, ART_HEIGHT),
    "--w": pct(x2 - x1, ART_WIDTH),
    "--h": pct(y2 - y1, ART_HEIGHT),
  } as CSSProperties;
}

export default function Cockpit({
  targets,
  selected,
  coordinates,
  catalogLoading,
  catalogError,
  onSelect,
  onCoordinates,
  onZoom,
  onCenter,
  onView,
  onRetry,
}: {
  targets: Target[];
  selected: Target | null;
  coordinates: Position | null;
  catalogLoading: boolean;
  catalogError: string;
  onSelect: (t: Target | null) => void;
  onCoordinates: (p: Position) => void;
  onZoom: (action: "in" | "out" | "all") => void;
  onCenter: (p: Position) => void;
  onView: () => void;
  onRetry: () => void;
}) {
  const [panelOpen, setPanelOpen] = useState(false);
  const switchButton = useRef<HTMLButtonElement>(null);
  const position: Position | null = selected
    ? { ra: selected.ra, dec: selected.dec }
    : coordinates;

  function closePanel() {
    setPanelOpen(false);
    // Return focus to the control that opened the dialog, as a keyboard user expects.
    switchButton.current?.focus();
  }

  return (
    <div className={s.cockpit} data-panel={panelOpen ? "open" : "closed"}>
      {panelOpen && (
        <>
          <div className={s.beam} aria-hidden="true" />
          <CoordinatePanel
            initial={position}
            onClose={closePanel}
            onApply={(p) => {
              onCoordinates(p);
              closePanel();
            }}
          />
        </>
      )}
      <img
        className={s.art}
        src="/panels/cockpit.webp"
        alt=""
        aria-hidden="true"
        width={ART_WIDTH}
        height={ART_HEIGHT}
        draggable={false}
      />
      <section className={s.console} aria-label="Sky navigation console">
        {/* Painted in the art on wide screens; shown as text on narrow ones. */}
        <h2 className={s.identity}>
          Navigation <span>All-sky survey</span>
        </h2>
        <label className={s.destination} style={place(575, 715, 1095, 745)}>
          <span className={s.paintedLabel}>Destination</span>
          <select
            value={selected?.slug ?? ""}
            onChange={(e) => onSelect(targets.find((t) => t.slug === e.target.value) ?? null)}
            disabled={catalogLoading || !!catalogError}
          >
            <option value="">Select object</option>
            {targets.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={`${s.control} ${s.locate}`}
          style={place(1111, 713, 1147, 746)}
          disabled={!position}
          aria-label="Centre the map on the destination"
          onClick={() => position && onCenter(position)}
        >
          <LocateFixed aria-hidden="true" />
        </button>
        <button
          ref={switchButton}
          type="button"
          className={`${s.control} ${s.switch}`}
          style={place(1202, 694, 1300, 746)}
          aria-expanded={panelOpen}
          aria-haspopup="dialog"
          onClick={() => (panelOpen ? closePanel() : setPanelOpen(true))}
        >
          <Crosshair aria-hidden="true" />
          <span className={s.paintedText}>RA / Dec</span>
        </button>
        <div className={s.position} aria-live="polite">
          <span className={s.paintedLabel}>Position / ICRS</span>
          <strong style={place(1311, 718, 1444, 743)}>
            {position ? `${position.ra.toFixed(3)}° / ${position.dec.toFixed(3)}°` : "Select target"}
          </strong>
        </div>
        <div className={s.zoom} role="group" aria-labelledby="cockpit-fov">
          {/* The art misspells this label, so it is always drawn live over it. */}
          <span id="cockpit-fov" className={s.fovLabel} style={place(1474, 698, 1566, 711)}>
            Field of view
          </span>
          <button type="button" className={s.control} style={place(1480, 716, 1512, 742)} aria-label="Zoom out" onClick={() => onZoom("out")}>
            <Minus aria-hidden="true" />
          </button>
          <button type="button" className={s.control} style={place(1516, 716, 1547, 742)} aria-label="Zoom in" onClick={() => onZoom("in")}>
            <Plus aria-hidden="true" />
          </button>
          <button type="button" className={s.control} style={place(1551, 716, 1616, 742)} onClick={() => onZoom("all")}>
            <span className={s.paintedText}>All sky</span>
          </button>
        </div>
        <button
          type="button"
          className={`${s.control} ${s.view}`}
          style={place(1657, 709, 1800, 760)}
          disabled={!position}
          onClick={onView}
        >
          <span className={s.paintedText}>View images</span>
          <ArrowRight aria-hidden="true" />
        </button>
        {(catalogLoading || catalogError) && (
          <p className={s.status} role={catalogError ? "alert" : "status"}>
            {catalogError || "Loading destinations…"}{" "}
            {catalogError && (
              <button type="button" onClick={onRetry}>
                Retry
              </button>
            )}
          </p>
        )}
      </section>
    </div>
  );
}
