"use client";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import { geoContains, geoGraticule10, geoOrthographic, geoPath } from "d3-geo";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import { feature } from "topojson-client";
import type { Topology } from "topojson-specification";
import { X } from "lucide-react";
import type { Target } from "@/lib/api";
import {
  angularDistance,
  decToParts,
  fovToFraction,
  fractionToFov,
  gmstDeg,
  hammer,
  hammerInverse,
  raToParts,
  subPoint,
  centreRadiusDeg,
} from "@/lib/coordinates";
import type { SkyLayers, SkyView } from "./Sky";
import s from "./cockpit.module.css";

type Position = { ra: number; dec: number };
export type Tab = "sky" | "objects" | "catalogs" | "tools";

/*
 * The cockpit art (public/panels/cockpit.webp) is the bottom of the design reference:
 * 1855 × 378 px, cut at y = 470 of the full 1855 × 848 frame. Live elements sit exactly over
 * the painted screens, so their boxes are written in reference pixels and turned into
 * percentages of the art.
 */
export const ART_WIDTH = 1855;
export const ART_HEIGHT = 378;
const ART_TOP = 470;
export function place(x1: number, y1: number, x2: number, y2: number) {
  const pct = (v: number, of: number) => `${(v / of) * 100}%`;
  return {
    "--l": pct(x1, ART_WIDTH),
    "--t": pct(y1 - ART_TOP, ART_HEIGHT),
    "--w": pct(x2 - x1, ART_WIDTH),
    "--h": pct(y2 - y1, ART_HEIGHT),
  } as CSSProperties;
}

const lat = (v: number) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? "N" : "S"}`;
const lon = (v: number) => `${Math.abs(v).toFixed(2)}°${v >= 0 ? "E" : "W"}`;
const hours = (deg: number) => {
  const p = raToParts(deg);
  return `${p.h}:${p.m}`;
};
function humanKind(kind: string) {
  const text = kind.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "Catalogued object";
}

/** Ticks once per second; the Earth turns 15″ of longitude per second under the sky. */
export function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

type Countries = Feature<Geometry, { name: string }>[];
let countriesPromise: Promise<Countries> | null = null;
/** Natural Earth 1:110m countries, loaded once and only when the cockpit is on screen. */
function loadCountries() {
  countriesPromise ??= import("world-atlas/countries-110m.json").then((m) => {
    const topo = (m.default ?? m) as unknown as Topology;
    const fc = feature(topo, topo.objects.countries) as unknown as FeatureCollection<Geometry, { name: string }>;
    return fc.features;
  });
  return countriesPromise;
}
function useCountries() {
  const [countries, setCountries] = useState<Countries>([]);
  useEffect(() => {
    let alive = true;
    loadCountries()
      .then((c) => alive && setCountries(c))
      .catch(() => {
        /* Without the outlines the globe still shows the graticule and the point. */
      });
    return () => {
      alive = false;
    };
  }, []);
  return countries;
}

/** Country under a point, or null over the sea (at 1:110m small islands are not resolved). */
function countryAt(countries: Countries, p: { lat: number; lon: number }) {
  return countries.find((c) => geoContains(c, [p.lon, p.lat]))?.properties.name ?? null;
}

/**
 * Everything the cockpit screens show is derived from these inputs, so they stay in step
 * with the map: `view` is what Aladin shows, `position` the chosen destination.
 */
export default function CockpitScreens({
  view,
  position,
  selected,
  targets,
  layers,
  tab,
  now,
  onTab,
  onLayers,
  onSelect,
  onClear,
  onGoto,
  onFov,
}: {
  view: SkyView | null;
  position: Position | null;
  selected: Target | null;
  targets: Target[];
  layers: SkyLayers;
  tab: Tab;
  now: Date;
  onTab: (t: Tab) => void;
  onLayers: (l: SkyLayers) => void;
  onSelect: (t: Target) => void;
  onClear: () => void;
  onGoto: (p: Position) => void;
  onFov: (fov: number) => void;
}) {
  const countries = useCountries();
  // Tools copy the destination when there is one, otherwise the map centre.
  const focus = position ?? (view ? { ra: view.ra, dec: view.dec } : null);
  // The Earth panels follow what the map shows; the destination only until the map reports a view.
  const centre = view ? { ra: view.ra, dec: view.dec } : position;
  const zenith = centre ? subPoint(centre.ra, centre.dec, now) : null;
  const ground = zenith ? countryAt(countries, zenith) : null;

  const nearest = useMemo(() => {
    if (!view || !targets.length) return null;
    return targets
      .map((t) => ({ t, d: angularDistance(view.ra, view.dec, t.ra, t.dec) }))
      .sort((a, b) => a.d - b.d)[0];
  }, [view, targets]);

  return (
    <div className={s.screens}>
      {/* Narrow screens have no painted cockpit: only this one-line summary is shown. */}
      <p className={s.zenithLine} aria-live="polite">
        {zenith
          ? `Overhead on Earth: ${lat(zenith.lat)} ${lon(zenith.lon)}${ground ? ` · ${ground}` : ""}`
          : "Overhead on Earth: —"}
      </p>
      <EarthGlobe
        countries={countries}
        zenith={zenith}
        onOpen={() => onTab("sky")}
      />

      <div className={s.titleScreen} style={place(276, 699, 390, 744)}>
        <strong>{selected?.name ?? (position ? "Custom position" : "Free flight")}</strong>
        <span>
          {selected
            ? humanKind(selected.kind)
            : position
              ? "Typed coordinates"
              : "View images uses the map centre"}
        </span>
        {position && (
          <button type="button" className={s.clearDestination} aria-label="Clear destination" title="Clear destination" onClick={onClear}>
            <X aria-hidden="true" />
          </button>
        )}
      </div>

      <div
        className={s.mfd}
        style={place(219, 753, 389, 826)}
        role="tabpanel"
        id="cockpit-mfd"
        aria-labelledby={`cockpit-tab-${tab}`}
      >
        {tab === "sky" && (
          <dl className={s.mfdList}>
            <div>
              <dt>Zenith over</dt>
              <dd>{zenith ? `${lat(zenith.lat)} · ${lon(zenith.lon)}` : "—"}</dd>
            </div>
            <div>
              <dt>Below it</dt>
              <dd>{zenith ? (ground ?? (countries.length ? "Open ocean" : "…")) : "—"}</dd>
            </div>
            <div>
              <dt>GMST</dt>
              <dd>{hours(gmstDeg(now))} sidereal</dd>
            </div>
          </dl>
        )}
        {tab === "objects" && (
          <ul className={s.mfdObjects}>
            {targets.map((t) => (
              <li key={t.slug}>
                <button type="button" aria-current={selected?.slug === t.slug} onClick={() => onSelect(t)}>
                  <span>{t.name}</span>
                  {view && <small>{angularDistance(view.ra, view.dec, t.ra, t.dec).toFixed(1)}°</small>}
                </button>
              </li>
            ))}
            {!targets.length && <li className={s.mfdEmpty}>Loading catalogue…</li>}
          </ul>
        )}
        {tab === "catalogs" && (
          <div className={s.mfdToggles}>
            <Toggle label="Nebo objects" on={layers.markers} onChange={(v) => onLayers({ ...layers, markers: v })} />
            <Toggle label="Landmarks" on={layers.landmarks} onChange={(v) => onLayers({ ...layers, landmarks: v })} />
            <Toggle label="Coordinate grid" on={layers.grid} onChange={(v) => onLayers({ ...layers, grid: v })} />
            <p>
              {targets.length} catalogued object{targets.length === 1 ? "" : "s"} · SPHEREx all-sky map
            </p>
          </div>
        )}
        {tab === "tools" && <Tools focus={focus} />}
      </div>

      {/*
        * Clock, all-sky locator and map centre share the wide slot under the light bar
        * (where the Destination picker was painted), clear of the radar dish below.
        */}
      <div className={s.clock} style={place(588, 707, 690, 750)} aria-label="Coordinated Universal Time">
        <span>UTC</span>
        <strong>{now.toISOString().slice(11, 19)}</strong>
        <small>{now.toISOString().slice(0, 10)}</small>
      </div>

      <SkyLocator view={view} targets={targets} selected={selected} onGoto={onGoto} />

      <div className={s.centerReadout} style={place(822, 708, 1010, 749)}>
        <span>Map centre</span>
        <strong>{view ? `${view.ra.toFixed(2)}° ${view.dec >= 0 ? "+" : "−"}${Math.abs(view.dec).toFixed(2)}°` : "—"}</strong>
        <small aria-hidden="true">Click the sky map to fly</small>
      </div>

      <FovGauge fov={view?.fov ?? null} onFov={onFov} />

      <button
        type="button"
        className={s.nearest}
        style={place(1426, 771, 1594, 821)}
        disabled={!nearest}
        onClick={() => nearest && onSelect(nearest.t)}
      >
        <span>Nearest catalogued object</span>
        <strong>{nearest?.t.name ?? "—"}</strong>
        <small>
          {nearest
            ? nearest.d <
              centreRadiusDeg(view?.fov, typeof window === "undefined" ? undefined : window.innerWidth)
              ? "At the map centre"
              : `${nearest.d.toFixed(nearest.d < 10 ? 2 : 1)}° from the map centre · go`
            : "Waiting for the map"}
        </small>
      </button>
    </div>
  );
}

function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={s.toggle} onClick={() => onChange(!on)}>
      <span>{label}</span>
      <i aria-hidden="true">{on ? "ON" : "OFF"}</i>
    </button>
  );
}

function Tools({ focus }: { focus: Position | null }) {
  const [copied, setCopied] = useState("");
  async function copy(kind: "deg" | "hms") {
    if (!focus) return;
    const text =
      kind === "deg"
        ? `${focus.ra.toFixed(5)} ${focus.dec.toFixed(5)}`
        : (() => {
            const r = raToParts(focus.ra), d = decToParts(focus.dec);
            return `${r.h}h${r.m}m${r.s}s ${d.sign}${d.d}°${d.m}′${d.s}″`;
          })();
    try {
      await navigator.clipboard.writeText(text);
      setCopied(kind);
    } catch {
      // Clipboard can be blocked (insecure origin, permissions); show the text to copy by hand.
      setCopied(text);
    }
  }
  return (
    <div className={s.mfdTools}>
      <button type="button" disabled={!focus} onClick={() => copy("deg")}>
        Copy RA/Dec · degrees
      </button>
      <button type="button" disabled={!focus} onClick={() => copy("hms")}>
        Copy RA/Dec · h m s
      </button>
      <p role="status">
        {copied === "deg" || copied === "hms" ? "Copied to the clipboard." : copied || "ICRS (J2000) position of the destination."}
      </p>
    </div>
  );
}

/**
 * Orthographic Earth always centred on the zenith point, i.e. the place on Earth where the map
 * centre is straight overhead right now. It cannot be turned by hand: it follows the map as the
 * person moves it, with or without a selected object. A click (or Enter) opens the Sky tab.
 */
function EarthGlobe({
  countries,
  zenith,
  onOpen,
}: {
  countries: Countries;
  zenith: { lat: number; lon: number } | null;
  onOpen: () => void;
}) {
  const size = 100;
  const centre = zenith ?? { lon: 0, lat: 0 };
  const projection = geoOrthographic()
    .scale(size / 2 - 3)
    .translate([size / 2, size / 2])
    .rotate([-centre.lon, -centre.lat])
    .clipAngle(90);
  const path = geoPath(projection);
  const point = zenith ? projection([zenith.lon, zenith.lat]) : null;
  const visible = !!zenith;
  return (
    <figure className={s.earth} style={place(20, 691, 197, 789)}>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={
          zenith
            ? `Earth globe. This sky is straight overhead at ${lat(zenith.lat)}, ${lon(zenith.lon)}.`
            : "Earth globe"
        }
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter") onOpen();
        }}
        onClick={onOpen}
      >
        <path className={s.earthSphere} d={path({ type: "Sphere" }) ?? ""} />
        <path className={s.earthGrid} d={path(geoGraticule10()) ?? ""} />
        {countries.map((c, i) => (
          <path key={i} className={s.earthLand} d={path(c) ?? ""} />
        ))}
        {visible && point && (
          <g className={s.earthDot} transform={`translate(${point[0]} ${point[1]})`}>
            <circle r="7" className={s.earthPulse} />
            <circle r="2.6" />
          </g>
        )}
      </svg>
      <figcaption>
        <span>Overhead on Earth</span>
        {zenith && (
          <>
            <strong>{lat(zenith.lat)}</strong>
            <strong>{lon(zenith.lon)}</strong>
          </>
        )}
      </figcaption>
    </figure>
  );
}

/** All-sky Hammer map: every catalogued object, the current view, and click-to-fly. */
function SkyLocator({
  view,
  targets,
  selected,
  onGoto,
}: {
  view: SkyView | null;
  targets: Target[];
  selected: Target | null;
  onGoto: (p: Position) => void;
}) {
  const W = 100, H = 50;
  const toSvg = (ra: number, dec: number) => {
    const p = hammer(ra, dec);
    return { x: W / 2 + (p.x * (W - 4)) / 2, y: H / 2 - (p.y * (H - 4)) / 2 };
  };
  const here = view ? toSvg(view.ra, view.dec) : null;
  const parallels = [-60, -30, 0, 30, 60];
  const meridians = [0, 60, 120, 180, 240, 300];
  const line = (pts: { x: number; y: number }[]) => pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`).join("");
  return (
    <svg
      className={s.locator}
      style={place(712, 706, 800, 750)}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="All-sky map. Click a point to fly the map there."
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const x = (((e.clientX - r.left) / r.width) * W - W / 2) / ((W - 4) / 2);
        const y = -(((e.clientY - r.top) / r.height) * H - H / 2) / ((H - 4) / 2);
        const p = hammerInverse(x, y);
        if (p) onGoto(p);
      }}
    >
      <ellipse cx={W / 2} cy={H / 2} rx={(W - 4) / 2} ry={(H - 4) / 2} className={s.locatorSky} />
      {parallels.map((d) => (
        <path key={`p${d}`} className={s.locatorGrid} d={line(Array.from({ length: 37 }, (_, i) => toSvg(i * 10, d)))} />
      ))}
      {meridians.map((ra) => (
        <path key={`m${ra}`} className={s.locatorGrid} d={line(Array.from({ length: 19 }, (_, i) => toSvg(ra + 1e-6, -90 + i * 10)))} />
      ))}
      {targets.map((t) => {
        const p = toSvg(t.ra, t.dec);
        return <circle key={t.slug} cx={p.x} cy={p.y} r={selected?.slug === t.slug ? 2.2 : 1.4} className={s.locatorTarget} />;
      })}
      {here && (
        <g className={s.locatorHere} transform={`translate(${here.x} ${here.y})`}>
          <circle r="3.2" />
          <path d="M-5 0H-2M2 0H5M0 -5V-2M0 2V5" />
        </g>
      )}
    </svg>
  );
}

/** Log-scale field-of-view gauge; also a slider (pointer or arrow keys) that zooms the map. */
function FovGauge({ fov, onFov }: { fov: number | null; onFov: (fov: number) => void }) {
  const t = fov === null ? 0 : fovToFraction(fov);
  const ticks = [0.1, 1, 10, 180];
  const fromPointer = (e: PointerEvent<HTMLDivElement>) => {
    const bar = e.currentTarget.querySelector<HTMLElement>("[data-track]")!.getBoundingClientRect();
    return fractionToFov((e.clientX - bar.left) / bar.width);
  };
  return (
    <div className={s.fovGauge} style={place(1204, 769, 1376, 821)}>
      <div className={s.fovHead}>
        <span id="cockpit-fov-gauge">Field of view</span>
        <strong>{fov === null ? "—" : fov >= 10 ? `${fov.toFixed(0)}°` : fov >= 1 ? `${fov.toFixed(1)}°` : `${(fov * 60).toFixed(1)}′`}</strong>
      </div>
      <div
        className={s.fovTrackArea}
        role="slider"
        tabIndex={0}
        aria-labelledby="cockpit-fov-gauge"
        aria-valuemin={0.1}
        aria-valuemax={180}
        aria-valuenow={fov === null ? undefined : Number(fov.toFixed(2))}
        aria-valuetext={fov === null ? undefined : `${fov.toFixed(2)} degrees`}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          onFov(fromPointer(e));
        }}
        onPointerMove={(e) => {
          if (e.currentTarget.hasPointerCapture(e.pointerId)) onFov(fromPointer(e));
        }}
        onKeyDown={(e) => {
          if (fov === null) return;
          // Each arrow press is one step of the map's own +/− buttons (×2).
          if (e.key === "ArrowRight" || e.key === "ArrowUp") onFov(Math.min(180, fov * 2));
          else if (e.key === "ArrowLeft" || e.key === "ArrowDown") onFov(Math.max(0.1, fov / 2));
          else if (e.key === "End") onFov(180);
          else if (e.key === "Home") onFov(0.1);
          else return;
          e.preventDefault();
        }}
      >
        <div className={s.fovTrack} data-track>
          {/* Bars rise with the zoom-out level, echoing the spectrum art that was here. */}
          {Array.from({ length: 40 }, (_, i) => (
            <i key={i} data-on={i / 39 <= t} style={{ height: `${25 + 75 * (i / 39)}%` }} />
          ))}
          <b style={{ left: `${t * 100}%` }} />
        </div>
        <div className={s.fovTicks} aria-hidden="true">
          {ticks.map((v) => (
            <span key={v} style={{ left: `${fovToFraction(v) * 100}%` }}>
              {v}°
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
