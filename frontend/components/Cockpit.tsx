"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Crosshair, Minus, Plus } from "lucide-react";
import type { Target } from "@/lib/api";
import CoordinatePanel from "./CoordinatePanel";
import CockpitScreens, { ART_HEIGHT, ART_WIDTH, place, useNow, type Tab } from "./CockpitScreens";
import type { SkyLayers, SkyMove, SkyView } from "./Sky";
import s from "./cockpit.module.css";

type Position = { ra: number; dec: number };

export default function Cockpit({
  targets,
  selected,
  coordinates,
  catalogLoading,
  catalogError,
  onSelect,
  onCoordinates,
  onZoom,
  onView,
  onRetry,
  skyView,
  layers,
  onLayers,
  onCommand,
  power = "on",
}: {
  targets: Target[];
  selected: Target | null;
  coordinates: Position | null;
  catalogLoading: boolean;
  catalogError: string;
  onSelect: (t: Target | null) => void;
  onCoordinates: (p: Position) => void;
  onZoom: (action: "in" | "out" | "all") => void;
  onView: () => void;
  onRetry: () => void;
  skyView: SkyView | null;
  layers: SkyLayers;
  onLayers: (l: SkyLayers) => void;
  onCommand: (move: SkyMove) => void;
  /**
   * The ship on the ground has its cockpit switched off (dark screens); "boot" plays the
   * power-up just before the jump.
   */
  power?: "off" | "boot" | "on";
}) {
  // "closing" keeps the hologram mounted while it dematerialises back into the beam.
  const [panel, setPanel] = useState<"closed" | "open" | "closing">("closed");
  const panelOpen = panel === "open";
  const [tab, setTab] = useState<Tab>("sky");
  const now = useNow();
  const switchButton = useRef<HTMLButtonElement>(null);
  const position: Position | null = selected
    ? { ra: selected.ra, dec: selected.dec }
    : coordinates;

  function closePanel() {
    // Return focus to the control that opened the dialog, as a keyboard user expects.
    switchButton.current?.focus();
    const reduced =
      document.documentElement.dataset.reduced === "true" ||
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    setPanel(reduced ? "closed" : "closing");
  }
  useEffect(() => {
    if (panel !== "closing") return;
    // Matches the 220 ms dematerialise + 60 ms beam delay in cockpit.module.css.
    const id = setTimeout(() => setPanel("closed"), 300);
    return () => clearTimeout(id);
  }, [panel]);

  return (
    <div className={s.cockpit} data-panel={panel} data-power={power} inert={power === "off"}>
      {panel !== "closed" && (
        <>
          <div className={s.beam} data-state={panel} aria-hidden="true">
            <span className={s.beamDust} />
          </div>
          <CoordinatePanel
            closing={panel === "closing"}
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
        {/* The four painted menu keys switch what the multi-function screen beside them shows. */}
        <div className={s.menu} role="tablist" aria-label="Cockpit screen">
          {(
            [
              ["sky", "Sky map", place(412, 695, 518, 720)],
              ["objects", "Objects", place(405, 728, 513, 755)],
              ["catalogs", "Catalogs", place(398, 762, 507, 788)],
              ["tools", "Tools", place(392, 797, 500, 823)],
            ] as const
          ).map(([id, label, box]) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`cockpit-tab-${id}`}
              aria-selected={tab === id}
              aria-controls="cockpit-mfd"
              className={`${s.control} ${s.menuKey}`}
              style={box}
              onClick={() => setTab(id)}
            >
              <span className={s.paintedText}>{label}</span>
            </button>
          ))}
        </div>
        <CockpitScreens
          view={skyView}
          position={position}
          selected={selected}
          targets={targets}
          layers={layers}
          tab={tab}
          now={now}
          onTab={setTab}
          onLayers={onLayers}
          // Picking the current destination again re-centres on it (after a drag, for example).
          onSelect={(t) =>
            t.slug === selected?.slug
              ? onCommand({ action: "center", ra: t.ra, dec: t.dec })
              : onSelect(t)
          }
          onGoto={(p) => onCommand({ action: "goto", ...p })}
          onFov={(fov) => onCommand({ action: "fov", fov })}
        />
        {/* Phones have no cockpit screens (and no OBJECTS tab), so they keep this picker. */}
        <label className={s.destination}>
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
          ref={switchButton}
          type="button"
          className={`${s.control} ${s.switch}`}
          style={place(1202, 694, 1300, 746)}
          aria-expanded={panelOpen}
          aria-haspopup="dialog"
          onClick={() => (panelOpen ? closePanel() : setPanel("open"))}
        >
          <Crosshair aria-hidden="true" />
          <span className={s.paintedText}>RA / Dec</span>
        </button>
        <div className={s.position} aria-live="polite">
          <span className={s.paintedLabel}>Position / ICRS</span>
          <strong style={place(1311, 718, 1444, 743)}>
            {position ? `${position.ra.toFixed(3)}° / ${position.dec.toFixed(3)}°` : "No destination"}
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
