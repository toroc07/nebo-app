"use client";
import { useEffect, useState } from "react";
import {
  diffImageUrl,
  epochDateRange,
  fetchPatchCandidates,
  imageUrl,
  type CandidateDetection,
  type Epoch,
  type Query,
  ApiError,
} from "@/lib/api";
import { changeLabel, changesSummary } from "@/lib/overlays";
import s from "./science.module.css";

export default function EpochDiffTriplet({
  patchId,
  query,
  detector,
  size,
  epochs,
  currentEpoch,
  widthPx = 59,
  heightPx = 59,
}: {
  patchId: number;
  query: Query;
  detector: number;
  size: string;
  epochs: Epoch[];
  currentEpoch: number;
  widthPx?: number;
  heightPx?: number;
}) {
  const [templateEpoch, setTemplateEpoch] = useState(0);
  const [showCandidates, setShowCandidates] = useState(true);
  const [candidates, setCandidates] = useState<CandidateDetection[]>([]);
  const [gaiaComplete, setGaiaComplete] = useState<number | null>(null);
  const [candError, setCandError] = useState("");
  const [truncated, setTruncated] = useState(false);
  const [summary, setSummary] = useState("");
  const [diffError, setDiffError] = useState(false);

  const compareEpoch = currentEpoch === templateEpoch && epochs.length > 1
    ? (templateEpoch + 1) % epochs.length
    : currentEpoch;

  const tpl = epochs[templateEpoch];
  const cmp = epochs[compareEpoch];

  useEffect(() => {
    if (epochs.length < 2) return;
    const abort = new AbortController();
    setCandError("");
    setCandidates([]);
    setTruncated(false);
    setSummary("");
    fetchPatchCandidates(
      patchId,
      { detector, size, epoch_a: templateEpoch, epoch_b: compareEpoch },
      abort.signal,
    )
      .then((res) => {
        setCandidates(res.candidates);
        setTruncated(res.truncated);
        setSummary(changesSummary(res));
        setGaiaComplete(res.gaia_complete_to_g);
      })
      .catch((e) => {
        if (!abort.signal.aborted) setCandError(
            // The generic 404 text ("could not find this object") is wrong here: the field exists.
            e instanceof ApiError && e.status === 404
              ? "Change candidates are unavailable for this field."
              : e.message || "Could not load candidates.",
          );
      });
    return () => abort.abort();
  }, [patchId, detector, size, templateEpoch, compareEpoch, epochs.length]);

  if (epochs.length < 2 || !tpl || !cmp) {
    return (
      <div className={s.panel}>
        <p className={s.note}>At least 2 epochs are required to compute a template-vs-new difference.</p>
      </div>
    );
  }

  const diffSrc = diffImageUrl(query, {
    a: templateEpoch,
    b: compareEpoch,
    detector,
    size,
  });

  return (
    <section className={s.panel} aria-label="Three-panel epoch difference comparison">
      <div className={s.panelHeader}>
        <h2 className={s.panelTitle}>Template · New Image · Difference</h2>
        <div className={s.badgeRow}>
          <span className={s.badgeMeasured}>Measured float32 diff</span>
        </div>
      </div>

      <div className={s.controls}>
        <label>
          Template epoch
          <select
            value={templateEpoch}
            onChange={(e) => setTemplateEpoch(Number(e.target.value))}
          >
            {epochs.map((ep, i) => (
              <option key={ep.index} value={i}>
                Epoch {i + 1} ({epochDateRange(ep.start_utc, ep.end_utc)})
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={showCandidates}
            onChange={(e) => setShowCandidates(e.target.checked)}
          />
          {/* A failed request must not read as "no changes". */}
          Show detected changes (
          {candError ? "unavailable" : summary || `${candidates.length}${truncated ? "+" : ""}`})
        </label>
      </div>

      <div className={s.tripletGrid}>
        <div className={s.tripletCard}>
          <h3>Template (Epoch {templateEpoch + 1})</h3>
          <div className={s.frameBox}>
            <img
              src={imageUrl(tpl.image_url)}
              alt={`Template epoch ${templateEpoch + 1}`}
            />
          </div>
        </div>

        <div className={s.tripletCard}>
          <h3>New Image (Epoch {compareEpoch + 1})</h3>
          <div className={s.frameBox}>
            <img
              src={imageUrl(cmp.image_url)}
              alt={`New image epoch ${compareEpoch + 1}`}
            />
          </div>
        </div>

        <div className={s.tripletCard}>
          <h3>Difference (E{compareEpoch + 1} − E{templateEpoch + 1})</h3>
          <div className={s.frameBox}>
            {diffError ? (
              <p className={s.note} style={{ padding: "1rem" }}>
                Float32 difference image unavailable for this timeline.
              </p>
            ) : (
              <img
                src={diffSrc}
                alt={`Difference between epoch ${compareEpoch + 1} and epoch ${templateEpoch + 1}`}
                onError={() => setDiffError(true)}
              />
            )}
            {showCandidates &&
              candidates.map((c, idx) => (
                <span
                  key={`${c.x}-${c.y}-${idx}`}
                  className={`${s.candidateMarker} ${
                    c.classification === "candidate_signal"
                      ? s.candidateSignal
                      : c.classification === "catalogued_systematic"
                        ? s.candidateSystematic
                        : s.candidateCatalogued
                  }`}
                  style={{
                    left: `${((c.x + 0.5) / widthPx) * 100}%`,
                    top: `${((c.y + 0.5) / heightPx) * 100}%`,
                  }}
                  title={`${changeLabel(c)} · SNR ${c.snr.toFixed(1)}`}
                />
              ))}
          </div>
        </div>
      </div>

      <p className={s.note}>
        Red = brighter in Epoch {compareEpoch + 1}, Blue = fainter, Black = unchanged, Transparent = no data.
        {" "}Changes are detected at 5σ after scaling the new epoch to the template and matching their PSFs;
        grey marks sit on static catalogued stars whose flux agrees in both epochs (likely PSF or
        wavelength residuals, not changes).
        {gaiaComplete !== null && ` Cross-matched against Gaia DR3 (complete to G = ${gaiaComplete.toFixed(1)}).`}
        {candError && ` (${candError})`}
      </p>
    </section>
  );
}
