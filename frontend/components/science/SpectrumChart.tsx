"use client";
import { useEffect, useState } from "react";
import {
  fetchModel2Spectrum,
  fetchPatchSpectrum,
  type Model2SpectrumResponse,
  type PatchSpectrumResponse,
} from "@/lib/api";
import s from "./science.module.css";

const BANDS = [
  { band: 1, min: 0.75, max: 1.09, fill: "rgba(63, 210, 255, 0.06)" },
  { band: 2, min: 1.10, max: 1.62, fill: "rgba(99, 102, 241, 0.06)" },
  { band: 3, min: 1.63, max: 2.41, fill: "rgba(168, 85, 247, 0.06)" },
  { band: 4, min: 2.42, max: 3.82, fill: "rgba(56, 189, 248, 0.08)" },
  { band: 5, min: 3.83, max: 4.41, fill: "rgba(251, 146, 60, 0.08)" },
  { band: 6, min: 4.42, max: 5.00, fill: "rgba(74, 222, 128, 0.08)" },
];

const MOLECULAR_LINES = [
  { um: 3.05, label: "H₂O" },
  { um: 3.20, label: "NH₃" },
  { um: 3.30, label: "CH₄/PAH" },
  { um: 3.53, label: "CH₃OH" },
  { um: 4.05, label: "Brα" },
  { um: 4.27, label: "CO₂" },
  { um: 4.67, label: "CO" },
];

export default function SpectrumChart({ patchId }: { patchId: number }) {
  const [spectrum, setSpectrum] = useState<PatchSpectrumResponse | null>(null);
  const [model2, setModel2] = useState<Model2SpectrumResponse | null>(null);
  const [bandFilter, setBandFilter] = useState<"all" | "mwir">("all");
  const [error, setError] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    setError("");
    Promise.all([
      fetchPatchSpectrum(patchId, -1, abort.signal),
      fetchModel2Spectrum(patchId, abort.signal),
    ])
      .then(([spec, m2]) => {
        setSpectrum(spec);
        setModel2(m2);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message || "Could not load spectrum.");
      });
    return () => abort.abort();
  }, [patchId]);

  if (error) {
    return (
      <section className={s.panel}>
        <p className={s.note}>{error}</p>
      </section>
    );
  }
  if (!spectrum) {
    return (
      <section className={s.panel}>
        <p className={s.note}>Loading 102-channel SPHEREx spectrum…</p>
      </section>
    );
  }
  // Nothing to draw: say why (a saturated star, too few clean channels) instead of a stand-in.
  if (spectrum.available === false) {
    return (
      <section className={s.panel} aria-label="102-channel SPHEREx spectrum">
        <div className={s.panelHeader}>
          <h2 className={s.panelTitle}>102-Channel SPHEREx Spectrum &amp; Model 2</h2>
          <div className={s.badgeRow}>
            <span className={s.badgeMeasured}>Not measurable here</span>
          </div>
        </div>
        <p className={s.note}>{spectrum.reason}</p>
      </section>
    );
  }

  const wMin = bandFilter === "mwir" ? 2.4 : 0.74;
  const wMax = 5.02;
  const channels = spectrum.channels.filter(
    (c) => c.lambda_c_um >= wMin && c.lambda_c_um <= wMax,
  );
  const validFluxes = channels
    .map((c) => c.flux_mjy)
    .filter((v): v is number => v !== null && Number.isFinite(v));
  const fMin = validFluxes.length ? Math.min(0, ...validFluxes) : 0;
  const fMax = validFluxes.length ? Math.max(...validFluxes) * 1.12 : 1;

  const W = 720;
  const H = 290;
  const pad = { l: 56, r: 18, t: 26, b: 40 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  const xOf = (um: number) => pad.l + ((um - wMin) / (wMax - wMin)) * plotW;
  const yOf = (flux: number) =>
    pad.t + plotH - ((flux - fMin) / Math.max(1e-9, fMax - fMin)) * plotH;

  // Split into contiguous polyline segments so BLANKCH (51-52, flux=null) stays an explicit gap.
  const segments: string[] = [];
  let currentPts: string[] = [];
  for (const ch of channels) {
    if (ch.flux_mjy === null || !Number.isFinite(ch.flux_mjy)) {
      if (currentPts.length) {
        segments.push(currentPts.join(" "));
        currentPts = [];
      }
      continue;
    }
    currentPts.push(`${xOf(ch.lambda_c_um).toFixed(1)},${yOf(ch.flux_mjy).toFixed(1)}`);
  }
  if (currentPts.length) segments.push(currentPts.join(" "));

  // A simulated spectrum (only for an explicit demo scenario) is a model curve: say so plainly
  // and hide the fit statistic, since a χ² of a model fitted to itself means nothing.
  const illustrative = Boolean(spectrum.simulated || model2?.simulated);
  const model2Ready = model2 && model2.available !== false;
  const poorFit = model2Ready && model2.citizen_level1?.fit_quality === "poor";

  return (
    <section
      className={s.panel}
      aria-label={illustrative ? "Illustrative model spectrum" : "102-channel SPHEREx spectrum and Model 2"}
    >
      <div className={s.panelHeader}>
        <h2 className={s.panelTitle}>
          {illustrative
            ? "Illustrative Model Spectrum (not measured)"
            : "102-Channel SPHEREx Spectrum & Molecular Indices"}
        </h2>
        <div className={s.badgeRow}>
          {illustrative ? (
            <span className={s.badgeSimulated}>Illustrative model · not SPHEREx data</span>
          ) : (
            <span className={s.badgeMeasured}>Measured · median per channel</span>
          )}
        </div>
      </div>
      {illustrative && (
        <p className={s.note} role="note">
          This curve is a model template drawn on the 102 SPHEREx channels, not a spectrum
          measured from this field&apos;s exposures. Use it to read where molecular bands fall,
          not as a result.
        </p>
      )}

      <div className={s.controls}>
        <label>
          Wavelength range
          <select
            value={bandFilter}
            onChange={(e) => setBandFilter(e.target.value as "all" | "mwir")}
          >
            <option value="all">Full SPHEREx (0.75–5.00 µm · Bands 1–6)</option>
            <option value="mwir">MWIR Ice &amp; Gas (2.40–5.00 µm · Bands 4–6)</option>
          </select>
        </label>
        {model2Ready && (
          <span className={s.mono}>
            {illustrative ? (
              <>
                Model template: <strong>{model2.best_template_name}</strong>
              </>
            ) : (
              <>
                Model 2{poorFit ? " (closest template, poor fit)" : ""}:{" "}
                <strong>{model2.predicted_class}</strong> · {model2.best_template_name} (χ²
                <sub>red</sub> = {model2.chi2_reduced.toFixed(2)})
              </>
            )}
          </span>
        )}
      </div>
      {!illustrative && poorFit && model2.citizen_level1?.fit_note && (
        <p className={s.note} role="note">
          {model2.citizen_level1.fit_note}
        </p>
      )}
      {model2 && model2.available === false && (
        <p className={s.note}>Model 2 not run: {model2.reason}</p>
      )}

      <div className={s.chartWrap}>
        <svg className={s.chartSvg} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="SPHEREx flux vs wavelength">
          {BANDS.filter((b) => b.max >= wMin).map((b) => {
            const x1 = Math.max(pad.l, xOf(b.min));
            const x2 = Math.min(W - pad.r, xOf(b.max));
            if (x2 <= x1) return null;
            return (
              <g key={b.band}>
                <rect x={x1} y={pad.t} width={x2 - x1} height={plotH} fill={b.fill} />
                <text
                  x={(x1 + x2) / 2}
                  y={pad.t + 14}
                  textAnchor="middle"
                  fill="#c1cbd3"
                  fontSize="10"
                  fontFamily="PlexMono, monospace"
                >
                  Band {b.band}
                </text>
              </g>
            );
          })}

          {bandFilter === "all" && (
            <rect
              x={xOf(2.38)}
              y={pad.t}
              width={Math.max(4, xOf(2.46) - xOf(2.38))}
              height={plotH}
              fill="rgba(255, 90, 90, 0.14)"
            />
          )}

          {MOLECULAR_LINES.filter((m) => m.um >= wMin && m.um <= wMax).map((m) => (
            <g key={m.label}>
              <line
                x1={xOf(m.um)}
                y1={pad.t + 18}
                x2={xOf(m.um)}
                y2={H - pad.b}
                stroke="rgba(255, 208, 128, 0.35)"
                strokeDasharray="3 3"
              />
              <text
                x={xOf(m.um)}
                y={H - pad.b - 6}
                textAnchor="middle"
                fill="#ffd080"
                fontSize="9.5"
                fontFamily="PlexMono, monospace"
              >
                {m.label}
              </text>
            </g>
          ))}

          <line x1={pad.l} y1={pad.t} x2={pad.l} y2={H - pad.b} stroke="#52616e" />
          <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke="#52616e" />

          {segments.map((pts, i) => (
            <polyline
              key={i}
              fill="none"
              stroke="#3fd2ff"
              strokeWidth="1.75"
              points={pts}
            />
          ))}

          <text x={W / 2} y={H - 8} textAnchor="middle" fill="#c1cbd3" fontSize="11">
            Wavelength (µm)
          </text>
          <text
            x={16}
            y={H / 2}
            textAnchor="middle"
            fill="#c1cbd3"
            fontSize="11"
            transform={`rotate(-90 16 ${H / 2})`}
          >
            Flux (mJy)
          </text>
        </svg>
      </div>

      {spectrum.indices && spectrum.indices.length > 0 && (
        <p className={s.note}>
          Top diagnostic indices:{" "}
          {spectrum.indices
            .slice(0, 5)
            .map((idx) => `${idx.index_code}: ${idx.value !== null ? idx.value.toFixed(3) : "—"}`)
            .join(" · ")}
          . Channels 51–52 (BLANKCH dichroic transition) are kept null and never imputed as 0.
        </p>
      )}
    </section>
  );
}
