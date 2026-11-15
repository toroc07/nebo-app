"use client";
import { useEffect, useState } from "react";
import {
  fetchCitizenVotes,
  fetchModel1Event,
  fetchModel3Forecast,
  fetchPatchMetrics,
  submitCitizenVote,
  type CitizenVote,
  type Model1EventResponse,
  type Model3ForecastResponse,
  type PatchMetricsResponse,
} from "@/lib/api";
import s from "./science.module.css";

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
  const forecast = model3.forecast_series ?? [];

  return (
    <section className={s.panel} aria-label="Metrics and coupled ML models">
      <div className={s.panelHeader}>
        <h2 className={s.panelTitle}>Metrics · Model 1 (Event) · Model 3 (GP Forecast)</h2>
        <div className={s.badgeRow}>
          {metricsData.image_photometry.length > 0 && (
            <span className={s.badgeMeasured}>Measured ePSF photometry</span>
          )}
          {(metricsData.simulated || model1.simulated || model3.simulated) && (
            <span className={s.badgeSimulated}>Simulated model profile</span>
          )}
        </div>
      </div>

      <div className={s.gridTwo}>
        <div className={s.subCard}>
          <h3>Model 1 · Event Attribution</h3>
          <p className={s.mono} style={{ margin: "0 0 0.4rem" }}>
            Class: <strong>{model1.predicted_class}</strong>
            {model1.citizen_level1?.confidence_score_pct !== undefined &&
              ` · ${model1.citizen_level1.confidence_score_pct}% confidence`}
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
        </div>

        <div className={s.subCard}>
          <h3>Model 3 · GP Forecast &amp; Astrometric Cone</h3>
          <p className={s.mono} style={{ margin: "0 0 0.4rem" }}>
            Status: <strong>{model3.citizen_level1?.alert_status ?? "NOMINAL"}</strong>
            {model3.z_alert !== undefined && ` · Z_alert = ${model3.z_alert.toFixed(2)}σ`}
          </p>
          {forecast.length > 1 && <GpForecastSparkline series={forecast} />}
          {model3.predicted_cone && (
            <p className={s.note}>
              Search cone (+{model3.predicted_cone.horizon_days} d): RA{" "}
              {model3.predicted_cone.ra_pred_deg.toFixed(5)}°, Dec{" "}
              {model3.predicted_cone.dec_pred_deg.toFixed(5)}° · 3σ radius{" "}
              {model3.predicted_cone.cone_radius_3s_arcsec.toFixed(2)}″
            </p>
          )}
          {model3.citizen_level1?.summary && (
            <p className={s.note}>{model3.citizen_level1.summary}</p>
          )}
        </div>
      </div>

      <div className={s.gridTwo} style={{ marginTop: "0.85rem" }}>
        <div className={s.subCard}>
          <h3>Measured ePSF Photometry (Detector D{detector})</h3>
          {metricsData.image_photometry.length === 0 ? (
            <p className={s.note}>No float32 (.npz) epoch photometry available for this detector.</p>
          ) : (
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Epoch</th>
                  <th>Flux</th>
                  <th>σ (3% floor)</th>
                  <th>SNR</th>
                  <th>Clean</th>
                </tr>
              </thead>
              <tbody>
                {metricsData.image_photometry.map((row) => (
                  <tr key={row.epoch_index}>
                    <td>E{row.epoch_index + 1}</td>
                    <td>{row.flux_hat.toFixed(3)}</td>
                    <td>{row.sigma_reported.toFixed(3)}</td>
                    <td>{row.snr.toFixed(1)}</td>
                    <td>{Math.round(row.p_clean_flags * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className={s.subCard}>
          <h3>Global Confidence &amp; Citizen Classification</h3>
          <p className={s.mono} style={{ margin: "0 0 0.4rem" }}>
            C_global: <strong>{metricsData.confidence.c_global.toFixed(1)} / 100</strong>
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
}: {
  series: Array<{ mjd: number; flux_mean_mjy: number; flux_std_mjy: number }>;
}) {
  const tMin = Math.min(...series.map((p) => p.mjd));
  const tMax = Math.max(...series.map((p) => p.mjd));
  const loVals = series.map((p) => p.flux_mean_mjy - 2 * p.flux_std_mjy);
  const hiVals = series.map((p) => p.flux_mean_mjy + 2 * p.flux_std_mjy);
  const fMin = Math.min(...loVals);
  const fMax = Math.max(...hiVals);

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
    </svg>
  );
}
