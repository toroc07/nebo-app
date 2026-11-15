"use client";
import { useEffect, useState } from "react";
import {
  fetchCitizenVotes,
  fetchModel1Event,
  fetchModel3Forecast,
  fetchPatchMetrics,
  submitCitizenVote,
  type CitizenVote,
  type ImagePhotometryPoint,
  type MeasuredLightCurve,
  type Model1EventResponse,
  type Model3ForecastResponse,
  type PatchMetricsResponse,
} from "@/lib/api";
import s from "./science.module.css";

const LOWER_LIMIT_NOTE =
  "Approximate lower limit: saturated pixels near the object are clipped or missing, so the real flux is higher.";

// Never present unchecked frames as clean: null saturation reads "n/a".
function saturationLabel(row: ImagePhotometryPoint): string {
  if (row.saturated === null) return "n/a";
  const unchecked = row.total_frames - row.checked_frames;
  return `${row.saturated_frames}/${row.checked_frames} frames${unchecked ? ` (+${unchecked} n/a)` : ""}`;
}

function saturationTitle(row: ImagePhotometryPoint): string {
  return `${row.checked_frames} of ${row.total_frames} frames checked for OVERFLOW/SUR_ERROR near the object`;
}

function modelEstimateLabel(simulated: boolean | undefined): string {
  return simulated
    ? "Model estimate, not a detection · simulated demo profile."
    : "Model estimate on this patch's SPHEREx measurements, not a detection.";
}

// Uncalibrated scores read as a coarse level, never as an exact percentage.
function likelihoodLevel(pct: number): string {
  return pct >= 70 ? "high" : pct >= 40 ? "medium" : "low";
}

const VOTE_CHOICES = [
  { id: "real_change", label: "Real change" },
  { id: "moving_object", label: "Moving object" },
  { id: "artifact", label: "Artifact / noise" },
  { id: "uncertain", label: "Uncertain" },
];

export default function ModelsAndMetricsPanel({
  patchId,
  detector,
  epochIndex,
}: {
  patchId: number;
  detector: number;
  epochIndex: number;
}) {
  const [metricsData, setMetricsData] = useState<PatchMetricsResponse | null>(null);
  const [model1, setModel1] = useState<Model1EventResponse | null>(null);
  const [model3, setModel3] = useState<Model3ForecastResponse | null>(null);
  const [votes, setVotes] = useState<CitizenVote[]>([]);
  const [voteStatus, setVoteStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const abort = new AbortController();
    setError("");
    Promise.all([
      fetchPatchMetrics(patchId, detector, abort.signal),
      fetchModel1Event(patchId, abort.signal),
      fetchModel3Forecast(patchId, abort.signal),
      fetchCitizenVotes(patchId, abort.signal).catch(() => []),
    ])
      .then(([m, m1, m3, v]) => {
        setMetricsData(m);
        setModel1(m1);
        setModel3(m3);
        setVotes(v);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message || "Could not load metrics and models.");
      });
    return () => abort.abort();
  }, [patchId, detector]);

  async function handleVote(choice: string) {
    setVoteStatus("Saving…");
    try {
      const saved = await submitCitizenVote(patchId, {
        epoch_index: epochIndex,
        vote: choice,
      });
      setVotes((prev) => [saved, ...prev]);
      setVoteStatus("Recorded");
    } catch {
      setVoteStatus("Could not save vote");
    }
  }

  if (error) {
    return (
      <section className={s.panel}>
        <p className={s.note}>{error}</p>
      </section>
    );
  }
  if (!metricsData || !model1 || !model3) {
    return (
      <section className={s.panel}>
        <p className={s.note}>Loading photometry metrics and ML models…</p>
      </section>
    );
  }

  const shapDrivers = model1.treeshap_values?.top_drivers ?? [];
  const maxShap = Math.max(
    0.01,
    ...shapDrivers.map((d) => Math.abs(d.phi ?? 0)),
  );
  const m1Ready = model1.available !== false;
  const m3Ready = model3.available !== false;
  const forecast = m3Ready ? (model3.forecast_series ?? []) : [];
  const observed = m3Ready ? model3.researcher_level2?.light_curve : undefined;
  const confidence = metricsData.confidence;

  return (
    <section className={s.panel} aria-label="Metrics and coupled ML models">
      <div className={s.panelHeader}>
        <h2 className={s.panelTitle}>Metrics · Model 1 (Event) · Model 3 (GP Forecast)</h2>
        <div className={s.badgeRow}>
          {metricsData.image_photometry.length > 0 && (
            <span className={s.badgeMeasured}>Measured ePSF photometry</span>
          )}
          {metricsData.simulated || model1.simulated || model3.simulated ? (
            <span className={s.badgeSimulated}>Simulated model profile</span>
          ) : (
            <span className={s.badgeMeasured}>Models on measured data</span>
          )}
        </div>
      </div>

      {/* Headline numbers first; the detail cards below carry the evidence. */}
      <div className={s.statRow}>
        <div className={s.stat}>
          <span className={s.statLabel}>Event class</span>
          <span className={s.statValue}>{m1Ready ? model1.predicted_class : "no event"}</span>
        </div>
        {m1Ready && model1.citizen_level1?.confidence_score_pct !== undefined && (
          <div className={s.stat}>
            <span className={s.statLabel}>Likelihood</span>
            <span className={s.statValue}>
              {likelihoodLevel(model1.citizen_level1.confidence_score_pct)}
            </span>
          </div>
        )}
        {confidence && (
          <div className={s.stat}>
            <span className={s.statLabel}>Global confidence</span>
            <span className={s.statValue}>
              {confidence.c_global.toFixed(1)}
              <small>/ 100</small>
            </span>
          </div>
        )}
        {/* A simulated light curve says nothing about this patch: no alert status for it. */}
        {!model3.simulated && m3Ready && (
          <div className={s.stat}>
            <span className={s.statLabel}>Alert status</span>
            <span className={s.statValue}>{model3.citizen_level1?.alert_status ?? "n/a"}</span>
          </div>
        )}
      </div>

      <div className={s.gridTwo}>
        <div className={s.subCard}>
          <h3>Model 1 · Event Attribution</h3>
          {!m1Ready ? (
            <p className={s.note}>{model1.reason}</p>
          ) : (
          <>
          <p className={s.note}>{modelEstimateLabel(model1.simulated)}</p>
          <p className={s.mono} style={{ margin: "0 0 0.4rem" }}>
            Class: <strong>{model1.predicted_class}</strong>
            {model1.citizen_level1?.confidence_score_pct !== undefined &&
              ` · ${likelihoodLevel(model1.citizen_level1.confidence_score_pct)} likelihood`}
          </p>
          <div className={s.barList}>
            {Object.entries(model1.probabilities)
              .sort((a, b) => b[1] - a[1])
              .map(([cls, prob]) => (
                <div key={cls} className={s.barRow}>
                  <span className={s.mono}>{cls}</span>
                  <div className={s.barTrack}>
                    <div
                      className={s.barFill}
                      style={{ width: `${Math.round(prob * 100)}%` }}
                    />
                  </div>
                  <span className={s.mono}>{Math.round(prob * 100)}%</span>
                </div>
              ))}
          </div>
          {shapDrivers.length > 0 && (
            <>
              <h3 style={{ marginTop: "0.75rem" }}>Top SHAP Drivers</h3>
              <div className={s.barList}>
                {shapDrivers.slice(0, 5).map((d) => {
                  const val = d.phi ?? 0;
                  return (
                    <div key={d.feature} className={s.barRow}>
                      <span className={s.mono}>{d.feature}</span>
                      <div className={s.barTrack}>
                        <div
                          className={val >= 0 ? s.barFill : s.barFillWarn}
                          style={{ width: `${Math.min(100, (Math.abs(val) / maxShap) * 100)}%` }}
                        />
                      </div>
                      <span className={s.mono}>{val >= 0 ? "+" : ""}{val.toFixed(2)}</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
          </>
          )}
        </div>

        <div className={s.subCard}>
          <h3>Model 3 · GP Forecast &amp; Astrometric Cone</h3>
          {!m3Ready ? (
            <p className={s.note}>{model3.reason}</p>
          ) : (
          <>
          <p className={s.note}>{modelEstimateLabel(model3.simulated)}</p>
          {/* A simulated light curve says nothing about this patch: no alert status for it. */}
          {model3.simulated ? (
            <p className={s.note}>
              The light curve is a simulated demo profile, so no alert status is shown.
            </p>
          ) : (
            <p className={s.mono} style={{ margin: "0 0 0.4rem" }}>
              Status: <strong>{model3.citizen_level1?.alert_status ?? "n/a"}</strong>
              {model3.z_alert !== undefined && ` · Z_alert = ${model3.z_alert.toFixed(2)}σ`}
            </p>
          )}
          {forecast.length > 1 && <GpForecastSparkline series={forecast} observed={observed} />}
          {observed && (
            <p className={s.note}>
              Dots: measured flux per visit ({observed.times_mjd.length} visits, relative to the
              object&apos;s own spectrum so the filter&apos;s wavelength sweep cancels; 1.5 %
              calibration error included). Line and band: the GP forecast.
            </p>
          )}
          {model3.predicted_cone && (
            <p className={s.note}>
              Search cone (+{model3.predicted_cone.horizon_days} d): RA{" "}
              {model3.predicted_cone.ra_pred_deg.toFixed(5)}°, Dec{" "}
              {model3.predicted_cone.dec_pred_deg.toFixed(5)}° · 3σ radius{" "}
              {model3.predicted_cone.cone_radius_3s_arcsec.toFixed(2)}″
            </p>
          )}
          {!model3.simulated && model3.citizen_level1?.summary && (
            <p className={s.note}>{model3.citizen_level1.summary}</p>
          )}
          </>
          )}
        </div>
      </div>

      <div className={s.gridTwo} style={{ marginTop: "0.85rem" }}>
        <div className={s.subCard}>
          <h3>Measured ePSF Photometry (Detector D{detector})</h3>
          {metricsData.image_photometry.length === 0 ? (
            <p className={s.note}>No float32 (.npz) epoch photometry available for this detector.</p>
          ) : (
            <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Epoch</th>
                  <th>Flux</th>
                  <th>σ (measured)</th>
                  <th>SNR</th>
                  <th>Saturation</th>
                  <th>Clean</th>
                </tr>
              </thead>
              <tbody>
                {metricsData.image_photometry.map((row) => (
                  <tr key={row.epoch_index}>
                    <td>E{row.epoch_index + 1}</td>
                    <td title={row.saturated ? LOWER_LIMIT_NOTE : undefined}>
                      {row.flux_hat === null
                        ? "n/a"
                        : `${row.saturated ? "≥" : ""}${row.flux_hat.toFixed(3)}`}
                    </td>
                    <td>{row.sigma_stat?.toFixed(3) ?? "n/a"}</td>
                    <td>{row.snr?.toFixed(1) ?? "n/a"}</td>
                    <td title={saturationTitle(row)}>{saturationLabel(row)}</td>
                    <td>{Math.round(row.p_clean_flags * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
          {metricsData.image_photometry.some((row) => row.saturated_frames > 0) && (
            <p className={s.note}>≥ {LOWER_LIMIT_NOTE}</p>
          )}
          {metricsData.image_photometry.some((row) => row.saturated === null) && (
            <p className={s.note}>
              Saturation n/a: some frames could not be checked, so the epoch is not known to be clean.
            </p>
          )}
        </div>

        <div className={s.subCard}>
          <h3>Global Confidence &amp; Citizen Classification</h3>
          <p className={s.mono} style={{ margin: "0 0 0.4rem" }}>
            C_global:{" "}
            <strong>
              {confidence ? `${confidence.c_global.toFixed(1)} / 100` : "n/a (no measured change)"}
            </strong>
          </p>
          <p className={s.note}>Classify this observed change ({votes.length} recorded):</p>
          <div className={s.voteRow}>
            {VOTE_CHOICES.map((c) => (
              <button
                key={c.id}
                type="button"
                className={s.voteBtn}
                onClick={() => handleVote(c.id)}
              >
                {c.label}
              </button>
            ))}
          </div>
          {voteStatus && <p className={s.note}>{voteStatus}</p>}
        </div>
      </div>
    </section>
  );
}

function GpForecastSparkline({
  series,
  observed,
}: {
  series: Array<{ mjd: number; flux_mean_mjy: number; flux_std_mjy: number }>;
  /** The measured visits the forecast was fitted to, drawn as dots with their error bars. */
  observed?: MeasuredLightCurve;
}) {
  const obsT = observed?.times_mjd ?? [];
  const obsF = observed?.fluxes_mjy ?? [];
  const obsS = observed?.sigmas_mjy ?? [];
  const obsLo = obsT.map((_, i) => obsF[i] - obsS[i]);
  const obsHi = obsT.map((_, i) => obsF[i] + obsS[i]);
  const tMin = Math.min(...series.map((p) => p.mjd), ...obsT);
  const tMax = Math.max(...series.map((p) => p.mjd), ...obsT);
  const loVals = series.map((p) => p.flux_mean_mjy - 2 * p.flux_std_mjy);
  const hiVals = series.map((p) => p.flux_mean_mjy + 2 * p.flux_std_mjy);
  const fMin = Math.min(...loVals, ...obsLo);
  const fMax = Math.max(...hiVals, ...obsHi);

  const W = 360;
  const H = 120;
  const pad = 14;
  const xOf = (t: number) =>
    pad + ((t - tMin) / Math.max(1e-6, tMax - tMin)) * (W - 2 * pad);
  const yOf = (f: number) =>
    H - pad - ((f - fMin) / Math.max(1e-6, fMax - fMin)) * (H - 2 * pad);

  const meanPts = series.map((p) => `${xOf(p.mjd).toFixed(1)},${yOf(p.flux_mean_mjy).toFixed(1)}`).join(" ");
  const upperPts = series.map((p) => `${xOf(p.mjd).toFixed(1)},${yOf(p.flux_mean_mjy + 2 * p.flux_std_mjy).toFixed(1)}`);
  const lowerPts = [...series]
    .reverse()
    .map((p) => `${xOf(p.mjd).toFixed(1)},${yOf(p.flux_mean_mjy - 2 * p.flux_std_mjy).toFixed(1)}`);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} aria-label="Gaussian Process light curve forecast">
      <polygon
        points={[...upperPts, ...lowerPts].join(" ")}
        fill="rgba(63, 210, 255, 0.16)"
      />
      <polyline fill="none" stroke="#3fd2ff" strokeWidth="1.75" points={meanPts} />
      {obsT.map((t, i) => (
        <g key={t}>
          <line x1={xOf(t)} x2={xOf(t)} y1={yOf(obsLo[i])} y2={yOf(obsHi[i])} stroke="#ffb347" strokeWidth="1" />
          <circle cx={xOf(t)} cy={yOf(obsF[i])} r="2.6" fill="#ffb347" />
        </g>
      ))}
    </svg>
  );
}
