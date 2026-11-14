"use client";
import { useEffect, useState } from "react";
import { Play, Pause, RotateCcw } from "lucide-react";
import {
  timeline,
  imageUrl,
  nextEpoch,
  ApiError,
  type Query,
  type Timeline,
  type Building,
} from "@/lib/api";
const stages: Record<string, string> = {
  queued: "Waiting for a turn",
  querying: "Searching for observations",
  downloading: "Downloading images",
  rendering: "Preparing images",
};
const bands = [
  "0.75–1.09 · Stars",
  "1.10–1.62 · Stars and red dwarfs",
  "1.63–2.41 · Variable stars",
  "2.42–3.82 · Stars with dust",
  "3.83–4.41 · Brown dwarfs",
  "4.42–5.00 · Coldest objects",
];
export default function Field({
  query,
  recommended,
  speed,
  reduced,
}: {
  query: Query;
  recommended: number;
  speed: number;
  reduced: boolean;
}) {
  const [detector, setDetector] = useState(recommended),
    [size, setSize] = useState("medium"),
    [data, setData] = useState<Timeline | null>(null),
    [progress, setProgress] = useState<Building | null>(null),
    [error, setError] = useState(""),
    [retryAt, setRetryAt] = useState(0),
    [now, setNow] = useState(Date.now()),
    [reload, setReload] = useState(0),
    [epoch, setEpoch] = useState(0),
    [playing, setPlaying] = useState(false),
    [interval, setIntervalMs] = useState(speed),
    [imageError, setImageError] = useState(false),
    [imageLoading, setImageLoading] = useState(true);
  useEffect(() => {
    setDetector(recommended);
  }, [recommended]);
  useEffect(() => {
    setIntervalMs(speed);
  }, [speed]);
  useEffect(() => {
    const abort = new AbortController();
    setData(null);
    setProgress(null);
    setError("");
    setPlaying(false);
    setEpoch(0);
    setRetryAt(0);
    timeline(query, size, detector, abort.signal, setProgress)
      .then((d) => {
        if (!abort.signal.aborted) {
          setData(d);
          setProgress(null);
        }
      })
      .catch((e: unknown) => {
        if (!abort.signal.aborted) {
          setError(
            e instanceof Error
              ? e.message
              : "The service response could not be read.",
          );
          if (e instanceof ApiError)
            setRetryAt(
              Date.now() +
                Math.max(e.retryAfter, e.status === 502 ? 60 : 0) * 1000,
            );
        }
      });
    return () => abort.abort();
  }, [query, size, detector, reload]);
  useEffect(() => {
    if (!error) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [error]);
  useEffect(() => {
    const stop = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener("visibilitychange", stop);
    return () => document.removeEventListener("visibilitychange", stop);
  }, []);
  useEffect(() => {
    if (reduced) setPlaying(false);
  }, [reduced]);
  useEffect(() => {
    if (!playing || !data || data.epochs.length < 2) return;
    const id = setInterval(
      () => setEpoch((e) => nextEpoch(e, data.epochs.length)),
      interval,
    );
    return () => clearInterval(id);
  }, [playing, data, interval]);
  const current = data?.epochs[epoch];
  useEffect(() => {
    setImageError(false);
    setImageLoading(true);
  }, [current?.image_url, reload]);
  const remaining = Math.max(0, Math.ceil((retryAt - now) / 1000));
  return (
    <section className="surface field">
      <div className="field-controls">
        <label>
          Detector
          <select
            value={detector}
            onChange={(e) => setDetector(Number(e.target.value))}
          >
            {bands.map((b, i) => (
              <option value={i + 1} key={b}>
                D{i + 1} · {b} µm
              </option>
            ))}
          </select>
        </label>
        <label>
          Field size
          <select value={size} onChange={(e) => setSize(e.target.value)}>
            <option value="small">3 arcminutes</option>
            <option value="medium">6 arcminutes</option>
            <option value="large">15 arcminutes</option>
          </select>
        </label>
        <span className="science-label">Observed change · SPHEREx QR2</span>
      </div>
      {error ? (
        <div className="notice" role="alert">
          <h2>We could not open this field</h2>
          <p>{error}</p>
          <button
            disabled={remaining > 0}
            className="action"
            onClick={() => setReload((x) => x + 1)}
          >
            <RotateCcw size={18} />
            {remaining > 0 ? `Retry in ${remaining} s` : "Retry"}
          </button>
        </div>
      ) : !data ? (
        <div className="field-loading" role="status">
          <div className="skeleton" />
          <h2>
            {progress
              ? stages[progress.progress.stage] || "Preparing the field"
              : "Checking images"}
          </h2>
          <p>
            A new field can take a few minutes. You can go back to the menu.
          </p>
          {progress && (
            <>
              <progress
                max={progress.progress.total || 1}
                value={
                  progress.progress.total ? progress.progress.done : undefined
                }
                aria-label="Field preparation"
              />
              <p>
                {progress.progress.total > 0
                  ? `${progress.progress.done} of ${progress.progress.total}`
                  : "Looking for available data…"}
              </p>
            </>
          )}
        </div>
      ) : !current ? (
        <p className="notice">
          This field has no epochs available yet. Try another detector or size.
        </p>
      ) : (
        <>
          <div className="field-display">
            <span className="north mono">N ↑</span>
            <span className="east mono">E ←</span>
            {imageLoading && !imageError && (
              <span role="status" className="image-status">
                Loading epoch…
              </span>
            )}
            {imageError ? (
              <p role="alert">
                This image could not be loaded.{" "}
                <button
                  className="secondary"
                  onClick={() => setReload((n) => n + 1)}
                >
                  Reload
                </button>
              </p>
            ) : (
              <img
                src={imageUrl(current.image_url)}
                alt={`Infrared image of the field observed on ${current.start_utc.slice(0, 10)}, detector ${detector}`}
                width={420}
                height={420}
                onLoad={() => setImageLoading(false)}
                onError={() => {
                  setImageError(true);
                  setImageLoading(false);
                  setPlaying(false);
                }}
              />
            )}
            <span className="reticle" aria-hidden="true" />
            <span className="scale mono">↔ {data.size.side_arcmin}′</span>
          </div>
          <div className="timeline-panel">
            <label htmlFor="epoch">
              Observation date ·{" "}
              {new Date(current.start_utc).toLocaleDateString("en", {
                timeZone: "UTC",
                day: "numeric",
                month: "long",
                year: "numeric",
              })}{" "}
              UTC
            </label>
            <input
              id="epoch"
              type="range"
              min="0"
              max={Math.max(0, data.epochs.length - 1)}
              step="1"
              value={epoch}
              disabled={data.epochs.length < 2}
              onChange={(e) => {
                setPlaying(false);
                setEpoch(Number(e.target.value));
              }}
            />
            <div className="button-row">
              <button
                className="action"
                disabled={data.epochs.length < 2 || imageError}
                onClick={() => setPlaying((p) => !p)}
              >
                {playing ? <Pause size={18} /> : <Play size={18} />}{" "}
                {playing ? "Pause" : "Compare epochs"}
              </button>
              <label>
                Interval
                <select
                  value={interval}
                  onChange={(e) => setIntervalMs(Number(e.target.value))}
                >
                  <option value="400">0.4 seconds</option>
                  <option value="800">0.8 seconds</option>
                  <option value="1500">1.5 seconds</option>
                </select>
              </label>
              <span className="mono">
                Epoch {epoch + 1} of {data.epochs.length}
              </span>
            </div>
            {data.epochs.length === 1 && (
              <p>Only one epoch is available; comparing needs at least two.</p>
            )}
            <p className="field-meta mono">
              RA {data.patch.ra.toFixed(5)}° · Dec {data.patch.dec.toFixed(5)}°
              · {data.detector.wavelength_range_um.join("–")} µm ·{" "}
              {data.size.pixel_scale_arcsec}″/px
            </p>
            <p>
              A change between images does not confirm a new object. Transparent
              areas have no data.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
