"use client";
import { useEffect, useId, useLayoutEffect, useRef, useState, type Ref } from "react";
import { Check, ChevronDown, ChevronUp, Info, LocateFixed, RotateCcw, X } from "lucide-react";
import {
  decToParts,
  partsToDec,
  partsToRa,
  raToParts,
  stepDec,
  stepRa,
  type DecParts,
  type RaParts,
} from "@/lib/coordinates";
import { validCoordinates } from "@/lib/api";
import ConsoleSelect from "./ConsoleSelect";
import s from "./cockpit.module.css";

type Position = { ra: number; dec: number };
type Format = "sexagesimal" | "degrees";
type RaUnit = "h" | "m" | "s";
type DecUnit = "d" | "m" | "s";

const emptyRa: RaParts = { h: "", m: "", s: "" };
const emptyDec: DecParts = { sign: "+", d: "", m: "", s: "" };

/**
 * Holographic RA/Dec entry projected from the cockpit radar.
 * It is a non-modal dialog: the map behind stays usable while it is open.
 */
export default function CoordinatePanel({
  initial,
  onApply,
  onClose,
  closing = false,
}: {
  initial: Position | null;
  onApply: (p: Position) => void;
  onClose: () => void;
  /** True while the panel plays its dematerialise animation before unmounting. */
  closing?: boolean;
}) {
  const id = useId();
  const [format, setFormat] = useState<Format>("sexagesimal");
  const [ra, setRa] = useState<RaParts>(initial ? raToParts(initial.ra) : emptyRa);
  const [dec, setDec] = useState<DecParts>(initial ? decToParts(initial.dec) : emptyDec);
  const [raDeg, setRaDeg] = useState(initial ? initial.ra.toFixed(5) : "");
  const [decDeg, setDecDeg] = useState(initial ? initial.dec.toFixed(5) : "");
  const [error, setError] = useState("");
  // The stepper arrows move whichever box was edited last; hours/degrees until then.
  const raUnit = useRef<RaUnit>("h");
  const decUnit = useRef<DecUnit>("d");
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => first.current?.focus(), []);

  /** Current value in degrees from whichever format is showing, or null if incomplete. */
  function read(): Position | null {
    if (format === "degrees") {
      return validCoordinates(raDeg, decDeg) ? { ra: Number(raDeg), dec: Number(decDeg) } : null;
    }
    const r = partsToRa(ra), d = partsToDec(dec);
    return r === null || d === null ? null : { ra: r, dec: d };
  }

  function show(p: Position | null, f: Format = format) {
    if (f === "degrees") {
      setRaDeg(p ? p.ra.toFixed(5) : "");
      setDecDeg(p ? p.dec.toFixed(5) : "");
    } else {
      setRa(p ? raToParts(p.ra) : emptyRa);
      setDec(p ? decToParts(p.dec) : emptyDec);
    }
  }

  function changeFormat(next: Format) {
    // Carry a complete value across formats; a half-typed one cannot be converted.
    show(read(), next);
    setFormat(next);
    setError("");
  }

  function step(axis: "ra" | "dec", direction: 1 | -1) {
    const p = read() ?? { ra: 0, dec: 0 };
    // In degree mode both arrows move by 1°: 1/15 of an hour of RA is one degree.
    const next =
      format === "degrees"
        ? axis === "ra"
          ? { ...p, ra: stepRa(p.ra, "h", direction / 15) }
          : { ...p, dec: stepDec(p.dec, "d", direction) }
        : axis === "ra"
          ? { ...p, ra: stepRa(p.ra, raUnit.current, direction) }
          : { ...p, dec: stepDec(p.dec, decUnit.current, direction) };
    show(next);
    setError("");
  }

  function apply() {
    const p = read();
    if (!p) {
      setError(
        format === "degrees"
          ? "Enter RA from 0 to less than 360°, and Dec from −90 to 90°."
          : "Enter RA as 0–23 h, 0–59 m, 0–59.99 s, and Dec from −90° to +90°.",
      );
      return;
    }
    onApply(p);
  }

  const position = read();
  const errorId = `${id}-error`;
  const describedBy = error ? errorId : undefined;

  return (
    <div
      className={s.holo}
      data-state={closing ? "closing" : "open"}
      role="dialog"
      aria-modal="false"
      aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <HoloFrame />
      <header className={s.holoHeader}>
        <LocateFixed className={s.holoIcon} aria-hidden="true" />
        <h2 id={`${id}-title`}>
          <span className={s.holoTitle}>Coordinates</span>
          <span className={s.holoDot} aria-hidden="true">·</span>
          <span className={s.holoSubtitle}>RA / Dec</span>
        </h2>
        <button type="button" className={s.holoClose} aria-label="Close coordinates" onClick={onClose}>
          <X aria-hidden="true" />
        </button>
      </header>
      <div className={s.holoBody}>
        <Globe position={position} />
        <form
          className={s.holoForm}
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
        >
          <fieldset className={s.holoField}>
            <legend>Right Ascension (RA)</legend>
            <div className={s.holoBox}>
              {format === "degrees" ? (
                <Segment ref={first} label="Right ascension in degrees" unit="°" placeholder="000.00000" value={raDeg} wide
                  onChange={setRaDeg} describedBy={describedBy} />
              ) : (
                <>
                  <Segment ref={first} label="Right ascension hours" unit="h" placeholder="00" value={ra.h} max={2}
                    onFocus={() => (raUnit.current = "h")} onChange={(v) => setRa({ ...ra, h: v })} describedBy={describedBy} />
                  <Segment label="Right ascension minutes" unit="m" placeholder="00" value={ra.m} max={2}
                    onFocus={() => (raUnit.current = "m")} onChange={(v) => setRa({ ...ra, m: v })} describedBy={describedBy} />
                  <Segment label="Right ascension seconds" unit="s" placeholder="00.00" value={ra.s} max={5}
                    onFocus={() => (raUnit.current = "s")} onChange={(v) => setRa({ ...ra, s: v })} describedBy={describedBy} />
                </>
              )}
              <Stepper axis="right ascension" onStep={(d) => step("ra", d)} />
            </div>
          </fieldset>
          <fieldset className={s.holoField}>
            <legend>Declination (Dec)</legend>
            <div className={s.holoBox}>
              {format === "degrees" ? (
                <Segment label="Declination in degrees" unit="°" placeholder="+00.00000" value={decDeg} wide signed
                  onChange={setDecDeg} describedBy={describedBy} />
              ) : (
                <>
                  <button
                    type="button"
                    className={s.holoSign}
                    aria-label={`Declination sign: ${dec.sign === "-" ? "south, negative" : "north, positive"}. Press to switch.`}
                    onClick={() => setDec({ ...dec, sign: dec.sign === "-" ? "+" : "-" })}
                  >
                    {dec.sign === "-" ? "−" : "+"}
                  </button>
                  <Segment label="Declination degrees" unit="°" placeholder="00" value={dec.d} max={2} tight
                    onFocus={() => (decUnit.current = "d")} onChange={(v) => setDec({ ...dec, d: v })} describedBy={describedBy} />
                  <Segment label="Declination arcminutes" unit="′" placeholder="00" value={dec.m} max={2}
                    onFocus={() => (decUnit.current = "m")} onChange={(v) => setDec({ ...dec, m: v })} describedBy={describedBy} />
                  <Segment label="Declination arcseconds" unit="″" placeholder="00.0" value={dec.s} max={4}
                    onFocus={() => (decUnit.current = "s")} onChange={(v) => setDec({ ...dec, s: v })} describedBy={describedBy} />
                </>
              )}
              <Stepper axis="declination" onStep={(d) => step("dec", d)} />
            </div>
          </fieldset>
          <div className={s.holoFormat}>
            <span aria-hidden="true">Format:</span>
            {/* Not a native <select>: its grey system list clashes with the holographic panel. */}
            <ConsoleSelect
              label="Format"
              hideLabel
              value={format}
              onChange={(v) => changeFormat(v as Format)}
              options={[
                { value: "sexagesimal", label: "HMS / DMS" },
                { value: "degrees", label: "Degrees" },
              ]}
              styles={{ control: s.holoPick, select: s.holoPickWrap, selectButton: s.holoPickButton, listbox: s.holoPickList }}
            />
            <span className={s.holoInfo}>
              <button type="button" aria-describedby={`${id}-info`} aria-label="About these coordinates">
                <Info aria-hidden="true" />
              </button>
              <span role="tooltip" id={`${id}-info`}>
                ICRS (J2000). RA runs 0–24 h eastward; Dec runs from −90° (south) to +90° (north).
                The arrows step the box you last edited.
              </span>
            </span>
          </div>
          {error && (
            <p id={errorId} className={s.holoError} role="alert">
              {error}
            </p>
          )}
          <div className={s.holoActions}>
            <button
              type="button"
              className={s.holoReset}
              onClick={() => {
                // Clear the form for a new entry. (It used to go back to the position the panel
                // opened with, which looked like nothing happened: that value was already shown.)
                setFormat("sexagesimal");
                setRa(emptyRa);
                setDec(emptyDec);
                setRaDeg("");
                setDecDeg("");
                setError("");
                raUnit.current = "h";
                decUnit.current = "d";
                first.current?.focus();
              }}
            >
              <RotateCcw aria-hidden="true" /> Reset
            </button>
            <button type="submit" className={s.holoApply}>
              <Check aria-hidden="true" /> Apply
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Segment({
  ref,
  label,
  unit,
  value,
  placeholder,
  max,
  wide,
  tight,
  signed,
  onChange,
  onFocus,
  describedBy,
}: {
  ref?: Ref<HTMLInputElement>;
  label: string;
  unit: string;
  value: string;
  placeholder?: string;
  max?: number;
  wide?: boolean;
  tight?: boolean;
  signed?: boolean;
  onChange: (v: string) => void;
  onFocus?: () => void;
  describedBy?: string;
}) {
  return (
    <span className={`${s.holoSegment} ${wide ? s.holoSegmentWide : ""} ${tight ? s.holoSegmentTight : ""}`}>
      <input
        ref={ref}
        inputMode={signed ? "text" : "decimal"}
        autoComplete="off"
        spellCheck={false}
        aria-label={label}
        aria-describedby={describedBy}
        maxLength={wide ? 12 : max}
        // `ch` sizing keeps each box as wide as its longest valid value, like the reference.
        style={{ width: `${(wide ? 10 : (max ?? 2)) + 0.4}ch` }}
        value={value}
        placeholder={placeholder}
        onFocus={(e) => {
          e.currentTarget.select();
          onFocus?.();
        }}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className={s.holoUnit} aria-hidden="true">{unit}</span>
    </span>
  );
}

function Stepper({ axis, onStep }: { axis: string; onStep: (d: 1 | -1) => void }) {
  return (
    <span className={s.holoStepper}>
      <button type="button" aria-label={`Increase ${axis}`} onClick={() => onStep(1)}>
        <ChevronUp aria-hidden="true" />
      </button>
      <button type="button" aria-label={`Decrease ${axis}`} onClick={() => onStep(-1)}>
        <ChevronDown aria-hidden="true" />
      </button>
    </span>
  );
}

/**
 * Chamfered double outline. Drawn in pixels from the measured size, because a
 * stretched viewBox would skew the 45° corners whenever the panel changes height.
 */
function HoloFrame() {
  const svg = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const node = svg.current?.parentElement;
    if (!node) return;
    const measure = () => setSize({ w: node.offsetWidth, h: node.offsetHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const { w, h } = size;
  const outline = (inset: number, c: number) => {
    const [l, t, r, b] = [inset, inset, w - inset, h - inset];
    return `M${l + c} ${t}H${r - c * 1.4}L${r} ${t + c * 1.4}V${b - c}L${r - c} ${b}H${l + c * 1.2}L${l} ${b - c * 1.2}V${t + c}Z`;
  };
  const c = Math.max(18, Math.min(34, w * 0.035));
  return (
    <svg ref={svg} className={s.holoFrame} width={w} height={h} aria-hidden="true">
      {w > 0 && (
        <>
          <path className={s.holoFill} d={outline(1, c)} />
          <path className={s.holoOuter} d={outline(1, c)} />
          <path className={s.holoInner} d={outline(c * 0.42, c * 0.8)} />
          {/* Brackets on the side walls and light bars on the top/bottom edges, as in the reference. */}
          <path className={s.holoAccent} d={`M3 ${h * 0.34}V${h * 0.48}M${w - 3} ${h * 0.12 + c}V${h * 0.3}M${w - 3} ${h * 0.6}V${h * 0.74}`} />
          <path className={s.holoBeamLine} d={`M${w * 0.3} 1H${w * 0.7}M${w * 0.32} ${h - 1}H${w * 0.68}`} />
        </>
      )}
    </svg>
  );
}

/** Wireframe celestial sphere; the magenta reticle marks the position being entered. */
function Globe({ position }: { position: Position | null }) {
  const cx = 150, cy = 150, r = 100;
  const meridians = [1, 0.92, 0.71, 0.38];
  const parallels = [-60, -30, 30, 60];
  let marker: { x: number; y: number } | null = null;
  if (position) {
    // Schematic front view: 0 h at the left limb, 12 h centred, 24 h at the right limb.
    const lat = (position.dec * Math.PI) / 180;
    marker = {
      x: cx + (position.ra / 180 - 1) * r * Math.cos(lat),
      y: cy - r * Math.sin(lat),
    };
  }
  // The viewBox hugs the ±90° labels so the sphere gets as much height as the form column allows.
  return (
    <svg className={s.holoGlobe} viewBox="0 18 300 274" aria-hidden="true">
      <defs>
        <radialGradient id="holo-sphere" cx="45%" cy="40%" r="60%">
          <stop offset="0" stopColor="#2fc8ff" stopOpacity=".14" />
          <stop offset="1" stopColor="#0a3550" stopOpacity=".05" />
        </radialGradient>
        <marker id="holo-arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10Z" fill="currentColor" />
        </marker>
      </defs>
      <g className={s.globeLines}>
        <circle cx={cx} cy={cy} r={r} fill="url(#holo-sphere)" />
        {meridians.map((k) => (
          <ellipse key={k} cx={cx} cy={cy} rx={r * k} ry={r} />
        ))}
        <line x1={cx} y1={cy - r} x2={cx} y2={cy + r} />
        {parallels.map((lat) => {
          const rad = (lat * Math.PI) / 180;
          return <ellipse key={lat} cx={cx} cy={cy - r * Math.sin(rad)} rx={r * Math.cos(rad)} ry={7 * Math.cos(rad)} />;
        })}
        <ellipse className={s.globeEquator} cx={cx} cy={cy} rx={r} ry={7} />
        <circle className={s.globeNode} cx={cx - r} cy={cy} r={2.6} />
        <circle className={s.globeNode} cx={cx + r} cy={cy} r={2.6} />
        <circle className={s.globeNode} cx={cx} cy={cy - r} r={2.6} />
        <circle className={s.globeNode} cx={cx} cy={cy + r} r={2.6} />
      </g>
      <g className={s.globeArrows}>
        <path d="M30 118Q36 76 70 52" markerEnd="url(#holo-arrow)" markerStart="url(#holo-arrow)" />
        <path d="M168 236Q200 236 228 228" markerEnd="url(#holo-arrow)" />
      </g>
      <g className={s.globeLabels}>
        <text x={cx} y={36} textAnchor="middle">+90°</text>
        <text x={cx} y={282} textAnchor="middle">−90°</text>
        <text x={18} y={cy + 5} textAnchor="middle">0h</text>
        <text x={cx + 16} y={cy - 2} textAnchor="middle">12h</text>
        <text x={cx + r + 26} y={cy + 5} textAnchor="middle">24h</text>
        <text className={s.globeAxis} x={28} y={64}>Dec</text>
        <text className={s.globeAxis} x={cx} y={240} textAnchor="middle">RA</text>
      </g>
      {marker && (
        <g className={s.globeMarker} transform={`translate(${marker.x} ${marker.y})`}>
          <circle r={5} />
          <path d="M-11 0H-6M6 0H11M0 -11V-6M0 6V11" />
        </g>
      )}
    </svg>
  );
}
