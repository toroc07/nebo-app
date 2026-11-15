"use client";
// Spectrum measured from this field's SPHEREx exposures (GET /patches/{id}/spectrum/measured):
// one point per usable exposure and the median per channel. Shown above the 102-channel medians
// and labelled MEASURED; when the object saturates the detector there is nothing honest to plot,
// and the panel says so instead of drawing lower limits.
import { useEffect, useState } from "react";
import { read } from "@/lib/api";
import s from "./science.module.css";

type Point = {
  wavelength_um: number;
  flux_ujy: number;
  sigma_ujy: number | null;
  detector: number;
  /** The light in the aperture peaks on a neighbour, not on the object (older APIs: absent). */
  blended?: boolean;
};
type Channel = { channel_id: number; wavelength_um: number; flux_ujy: number; sigma_ujy: number | null; n: number };
type Measured = {
  points: Point[];
  channels: Channel[];
  excluded_saturated: number;
  excluded_missing: number;
  /** Local sky level subtracted (older APIs: absent, i.e. not subtracted). */
  background_subtracted?: boolean;
  blended_points?: number;
  note: string;
};

const POINT = "rgb(63 210 255 / 0.7)";
/** Grey, as the field viewer greys out likely systematics: drawn, but not the object's light. */
const BLENDED = "rgb(170 180 190 / 0.85)";

/** Fewer usable exposures than this is not a spectrum. */
const MIN_POINTS = 8;
const W = 640,
  H = 260,
  PAD = { l: 58, r: 14, t: 12, b: 30 };

export default function MeasuredSpectrum({ patchId }: { patchId: number }) {
  const [data, setData] = useState<Measured | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    setData(null);
    setError(false);
    read<Measured>(`/patches/${patchId}/spectrum/measured`, abort.signal)
      .then(setData)
      .catch(() => !abort.signal.aborted && setError(true));
    return () => abort.abort();
  }, [patchId]);

  const header = (
    <div className={s.panelHeader}>
      <h2 className={s.panelTitle}>Measured SPHEREx Spectrum</h2>
      <div className={s.badgeRow}>
        <span className={s.badgeMeasured}>Measured · SPHEREx exposures</span>
        {data && data.points.length > 0 && (
          <span className={s.badgeMeasured}>
            {data.background_subtracted ? "Local sky subtracted" : "Sky not subtracted"}
          </span>
        )}
      </div>
    </div>
  );
  if (error)
    return (
      <section className={s.panel} aria-label="Measured spectrum">
        {header}
        <p className={s.note}>The measured spectrum could not be loaded.</p>
      </section>
    );
  if (!data)
    return (
      <section className={s.panel} aria-label="Measured spectrum">
        {header}
        <p className={s.note}>Measuring the spectrum from the exposures…</p>
      </section>
    );
  if (data.points.length < MIN_POINTS)
    return (
      <section className={s.panel} aria-label="Measured spectrum">
        {header}
        <p className={s.note}>
          Not enough clean exposures to measure a spectrum ({data.points.length} usable,{" "}
          {data.excluded_saturated} saturated near the object). A saturated star only gives lower
          limits, so nothing is plotted.
        </p>
      </section>
    );

  // Axes: wavelength 0.7–5.0 µm; flux between robust percentiles so a few outliers do not
  // flatten the curve (points outside are clamped to the edge and drawn hollow).
  const fluxes = data.points.map((p) => p.flux_ujy).sort((a, b) => a - b);
  const q = (f: number) => fluxes[Math.min(fluxes.length - 1, Math.max(0, Math.round(f * (fluxes.length - 1))))];
  let lo = q(0.02),
    hi = q(0.98);
  if (hi - lo < 1e-9) hi = lo + 1;
  const span = hi - lo;
  lo -= span * 0.08;
  hi += span * 0.08;
  const x = (lam: number) => PAD.l + ((lam - 0.7) / (5.0 - 0.7)) * (W - PAD.l - PAD.r);
  const y = (f: number) => H - PAD.b - ((Math.min(hi, Math.max(lo, f)) - lo) / (hi - lo)) * (H - PAD.t - PAD.b);
  const out = (f: number) => f < lo || f > hi;
  const line = data.channels.map((c) => `${x(c.wavelength_um).toFixed(1)},${y(c.flux_ujy).toFixed(1)}`).join(" ");
  const yTicks = [lo, (lo + hi) / 2, hi];
  const midY = PAD.t + (H - PAD.t - PAD.b) / 2;

  return (
    <section className={s.panel} aria-label="Measured spectrum">
      {header}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`Measured spectrum: ${data.points.length} exposures from 0.7 to 5 microns, median per channel drawn as a line.`}
      >
        <rect x={PAD.l} y={PAD.t} width={W - PAD.l - PAD.r} height={H - PAD.t - PAD.b} fill="none" stroke="rgb(63 210 255 / 0.25)" />
        {[1, 2, 3, 4, 5].map((lam) => (
          <g key={lam}>
            <line x1={x(lam)} x2={x(lam)} y1={PAD.t} y2={H - PAD.b} stroke="rgb(63 210 255 / 0.12)" />
            <text x={x(lam)} y={H - 10} fill="#8fb6c8" fontSize="13" textAnchor="middle">
              {lam} µm
            </text>
          </g>
        ))}
        {yTicks.map((f, i) => (
          <text key={i} x={PAD.l - 6} y={y(f) + 4} fill="#8fb6c8" fontSize="12" textAnchor="end">
            {Math.abs(f) >= 1000 ? `${(f / 1000).toFixed(1)}k` : f.toFixed(0)}
          </text>
        ))}
        <text x={12} y={midY} fill="#8fb6c8" fontSize="12" textAnchor="middle" transform={`rotate(-90 12 ${midY})`}>
          flux (µJy)
        </text>
        {data.points.map((p, i) => (
          <circle
            key={i}
            cx={x(p.wavelength_um)}
            cy={y(p.flux_ujy)}
            r={2.2}
            fill={out(p.flux_ujy) || p.blended ? "none" : "rgb(63 210 255 / 0.45)"}
            stroke={p.blended ? BLENDED : POINT}
            strokeWidth={out(p.flux_ujy) || p.blended ? 1 : 0}
          />
        ))}
        <polyline points={line} fill="none" stroke="#ffb347" strokeWidth={1.6} />
      </svg>
      <p className={s.note}>
        {data.points.length} exposures measured ({data.channels.length} channels; amber line = median per channel)
        {data.blended_points
          ? ` · ${data.blended_points} hollow grey point${data.blended_points === 1 ? "" : "s"}: the light peaks on a neighbour, not on the object, so ${data.blended_points === 1 ? "it is" : "they are"} left out of the line`
          : ""}
        {data.excluded_saturated ? ` · ${data.excluded_saturated} saturated near the object left out` : ""}.{" "}
        {data.note}
      </p>
    </section>
  );
}
