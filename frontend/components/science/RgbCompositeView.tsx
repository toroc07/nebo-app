"use client";
import { useEffect, useState } from "react";
import { read, rgbImageUrl, type Patch, type Query } from "@/lib/api";
import s from "./science.module.css";

const DETECTORS = [
  { id: 1, label: "D1 (0.75–1.09 µm)" },
  { id: 2, label: "D2 (1.10–1.62 µm)" },
  { id: 3, label: "D3 (1.63–2.41 µm)" },
  { id: 4, label: "D4 (2.42–3.82 µm)" },
  { id: 5, label: "D5 (3.83–4.41 µm)" },
  { id: 6, label: "D6 (4.42–5.00 µm)" },
];

const PRESETS = [
  { label: "Cold Dust / Brown Dwarfs (D6 / D3 / D1)", r: 6, g: 3, b: 1 },
  { label: "Ices & Gas (D5 / D4 / D2)", r: 5, g: 4, b: 2 },
  { label: "Near-IR Stars (D3 / D2 / D1)", r: 3, g: 2, b: 1 },
];

export default function RgbCompositeView({
  patchId,
  query,
  size,
  epoch,
  onBuildDetector,
}: {
  patchId: number;
  query: Query;
  size: string;
  epoch: number;
  onBuildDetector?: (detector: number) => void;
}) {
  const [rDet, setRDet] = useState(6);
  const [gDet, setGDet] = useState(3);
  const [bDet, setBDet] = useState(1);
  const [readyDetectors, setReadyDetectors] = useState<number[] | null>(null);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    const abort = new AbortController();
    read<Patch[]>("/patches", abort.signal)
      .then((patches) => {
        const found = patches.find((p) => p.id === patchId);
        setReadyDetectors(found?.detectors_ready ?? []);
      })
      .catch(() => setReadyDetectors(null));
    return () => abort.abort();
  }, [patchId]);

  const missing =
    readyDetectors === null
      ? []
      : [...new Set([rDet, gDet, bDet])].filter((d) => !readyDetectors.includes(d));

  const src = rgbImageUrl(query, { r: rDet, g: gDet, b: bDet, epoch, size });

  return (
    <section className={s.panel} aria-label="False-color infrared RGB composite">
      <div className={s.panelHeader}>
        <h2 className={s.panelTitle}>False-Color Infrared RGB Composite</h2>
        <div className={s.badgeRow}>
          <span className={s.badgeMeasured}>Measured 3-band composite</span>
        </div>
      </div>

      <div className={s.controls}>
        <label>
          Preset
          <select
            value={`${rDet}-${gDet}-${bDet}`}
            onChange={(e) => {
              const [r, g, b] = e.target.value.split("-").map(Number);
              if (r && g && b) {
                setRDet(r);
                setGDet(g);
                setBDet(b);
                setImgError(false);
              }
            }}
          >
            {PRESETS.map((p) => (
              <option key={p.label} value={`${p.r}-${p.g}-${p.b}`}>
                {p.label}
              </option>
            ))}
            <option value="custom" disabled>
              Custom
            </option>
          </select>
        </label>
        <label>
          Red
          <select
            value={rDet}
            onChange={(e) => {
              setRDet(Number(e.target.value));
              setImgError(false);
            }}
          >
            {DETECTORS.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Green
          <select
            value={gDet}
            onChange={(e) => {
              setGDet(Number(e.target.value));
              setImgError(false);
            }}
          >
            {DETECTORS.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Blue
          <select
            value={bDet}
            onChange={(e) => {
              setBDet(Number(e.target.value));
              setImgError(false);
            }}
          >
            {DETECTORS.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {missing.length > 0 || imgError ? (
        <div className={s.missingBox}>
          <p style={{ marginTop: 0 }}>
            <strong>Missing detector data for this RGB combination.</strong>{" "}
            {missing.length > 0
              ? `Ready detectors on this patch: ${readyDetectors?.length ? readyDetectors.map((d) => `D${d}`).join(", ") : "none"}. Missing: ${missing.map((d) => `D${d}`).join(", ")}.`
              : "One or more selected detectors do not have float32 arrays for this epoch yet."}
          </p>
          {onBuildDetector && missing.length > 0 && (
            <div className={s.voteRow}>
              {missing.map((d) => (
                <button
                  key={d}
                  type="button"
                  className={s.voteBtn}
                  onClick={() => onBuildDetector(d)}
                >
                  Load Detector D{d}
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className={s.rgbStage}>
          <div className={s.frameBox}>
            <img
              src={src}
              alt={`False-color RGB composite using D${rDet} (red), D${gDet} (green), D${bDet} (blue)`}
              onError={() => setImgError(true)}
            />
          </div>
        </div>
      )}

      <div className={s.legendRow}>
        <div className={s.legendItem}>
          <span className={s.legendDot} style={{ background: "#e5484d" }} />
          <strong>Red (D{rDet})</strong>
          <span>Long wavelength</span>
        </div>
        <div className={s.legendItem}>
          <span className={s.legendDot} style={{ background: "#30a46c" }} />
          <strong>Green (D{gDet})</strong>
          <span>Medium wavelength</span>
        </div>
        <div className={s.legendItem}>
          <span className={s.legendDot} style={{ background: "#3b82f6" }} />
          <strong>Blue (D{bDet})</strong>
          <span>Short wavelength</span>
        </div>
      </div>
    </section>
  );
}
