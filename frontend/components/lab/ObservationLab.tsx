"use client";
// Observation module lab: loads each epoch's image and covers the basics (preload, blink,
// slider, expected-position marker, metadata). Deliberately unstyled: the look is decided by
// the menu. Kept isolated in components/lab/.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  epochImageUrl,
  loadTargets,
  loadTimeline,
  type LabTarget,
  type LabTimeline,
  type Source,
} from "@/lib/lab/contract";
import s from "./lab.module.css";

const sizes = ["small", "medium", "large"];

// `expected_position.x/y` is a 0-based pixel index, drawn at the pixel's centre. If the marker
// ever lands half a pixel off, this is the only number to adjust.
const PIXEL_CENTER_OFFSET = 0.5;

type Preload = { loaded: number; total: number; ms: number | null };

export default function ObservationLab() {
  const [source, setSource] = useState<Source>("demo");
  const [targets, setTargets] = useState<LabTarget[]>([]);
  const [slug, setSlug] = useState("barnards-star");
  const [detector, setDetector] = useState(3);
  const [size, setSize] = useState("medium");
  const [data, setData] = useState<LabTimeline | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [preload, setPreload] = useState<Preload>({
    loaded: 0,
    total: 0,
    ms: null,
  });
  const [epoch, setEpoch] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [interval, setIntervalMs] = useState(800);
  const [marker, setMarker] = useState(true);
  const [imageError, setImageError] = useState(false);
  const ready = preload.total > 0 && preload.loaded === preload.total;

  useEffect(() => {
    const abort = new AbortController();
    setError("");
    loadTargets(source)
      .then((t) => !abort.signal.aborted && setTargets(t))
      .catch((e: Error) => !abort.signal.aborted && setError(e.message));
    return () => abort.abort();
  }, [source]);

  // Every selection change requests a new timeline and resets playback.
  useEffect(() => {
    const abort = new AbortController();
    setData(null);
    setError("");
    setStatus("Loading…");
    setEpoch(0);
    setPlaying(false);
    setImageError(false);
    setPreload({ loaded: 0, total: 0, ms: null });
    loadTimeline(
      source,
      slug,
      detector,
      size,
      abort.signal,
      (stage, done, total) => setStatus(`Building: ${stage} ${done}/${total}`),
    )
      .then((d) => {
        if (abort.signal.aborted) return;
        setData(d);
        setStatus("");
      })
      .catch((e: Error) => {
        if (abort.signal.aborted) return;
        setError(e.message);
        setStatus("");
      });
    return () => abort.abort();
  }, [source, slug, detector, size]);

  // Preload every epoch before allowing blink, and time it to learn whether a strip of
  // images should be requested from the backend.
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    const started = performance.now();
    const total = data.epochs.length;
    setPreload({ loaded: 0, total, ms: null });
    let loaded = 0;
    data.epochs.forEach((e) => {
      const img = new Image();
      const done = () => {
        if (cancelled) return;
        loaded += 1;
        setPreload({
          loaded,
          total,
          ms: loaded === total ? Math.round(performance.now() - started) : null,
        });
      };
      img.onload = done;
      img.onerror = () => {
        if (cancelled) return;
        setImageError(true);
        done();
      };
      img.src = epochImageUrl(source, e);
    });
    return () => {
      cancelled = true;
    };
  }, [data, source]);

  const count = data?.epochs.length ?? 0;
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!playing || count < 2 || !ready) return;
    timer.current = setInterval(
      () => setEpoch((e) => (e + 1) % count),
      interval,
    );
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, count, interval, ready]);

  const current = data?.epochs[epoch];
  const releases = useMemo(
    () => [...new Set(data?.epochs.flatMap((e) => e.releases ?? []))],
    [data],
  );
  const position = current?.expected_position;

  return (
    <main className={s.lab}>
      <a href="/">← Back to the menu</a>
      <h1>Observation lab</h1>
      <p className={s.note}>
        Test route, linked from Observe. The demo source uses the synthetic
        images in shared/demo (do not judge contrast by them).
      </p>

      <div className={s.controls}>
        <label>
          Source
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as Source)}
          >
            <option value="demo">Demo (shared/demo)</option>
            <option value="api">Real API</option>
          </select>
        </label>
        <label>
          Object
          <select value={slug} onChange={(e) => setSlug(e.target.value)}>
            {(targets.length ? targets : [{ slug, name: slug }]).map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Detector
          <select
            value={detector}
            onChange={(e) => setDetector(Number(e.target.value))}
          >
            {(source === "demo" ? [3, 6] : [1, 2, 3, 4, 5, 6]).map((d) => (
              <option key={d} value={d}>
                D{d}
              </option>
            ))}
          </select>
        </label>
        <label>
          Size
          <select value={size} onChange={(e) => setSize(e.target.value)}>
            {sizes.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
        </label>
      </div>

      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}

      {data && current && (
        <div className={s.body}>
          <div>
            <div
              className={s.frame}
              style={{
                aspectRatio: `${data.size.width_px} / ${data.size.height_px}`,
              }}
            >
              {imageError ? (
                <p role="alert">This epoch's image could not be loaded.</p>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={epochImageUrl(source, current)}
                  alt={`Epoch ${epoch + 1} of ${count}, ${current.start_utc.slice(0, 10)}`}
                  className={s.image}
                />
              )}
              {marker && position?.in_image && (
                <span
                  className={s.marker}
                  title={`Expected position RA ${position.ra.toFixed(5)} Dec ${position.dec.toFixed(5)}`}
                  style={{
                    left: `${((position.x + PIXEL_CENTER_OFFSET) / data.size.width_px) * 100}%`,
                    top: `${((position.y + PIXEL_CENTER_OFFSET) / data.size.height_px) * 100}%`,
                  }}
                />
              )}
            </div>
            <p className={s.mono}>
              N up · E left · {data.size.side_arcmin}′ · {data.size.width_px}×
              {data.size.height_px}px
            </p>
          </div>

          <div className={s.panel}>
            <label>
              Epoch {epoch + 1} of {count} · {current.start_utc.slice(0, 10)}{" "}
              UTC
              <input
                type="range"
                min={0}
                max={Math.max(0, count - 1)}
                value={epoch}
                disabled={count < 2}
                onChange={(e) => {
                  setPlaying(false);
                  setEpoch(Number(e.target.value));
                }}
              />
            </label>
            <div className={s.row}>
              <button
                disabled={count < 2 || !ready || imageError}
                onClick={() => setPlaying((p) => !p)}
              >
                {playing ? "Pause" : "Blink"}
              </button>
              <label>
                Interval
                <select
                  value={interval}
                  onChange={(e) => setIntervalMs(Number(e.target.value))}
                >
                  <option value={400}>0.4 s</option>
                  <option value={800}>0.8 s</option>
                  <option value={1500}>1.5 s</option>
                </select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={marker}
                  onChange={(e) => setMarker(e.target.checked)}
                />
                Expected position
              </label>
            </div>

            <dl className={s.meta}>
              <dt>Preload</dt>
              <dd>
                {preload.loaded}/{preload.total}
                {preload.ms !== null && ` · ${preload.ms} ms`}
              </dd>
              <dt>Data release</dt>
              <dd>{releases.length ? releases.join(", ") : "not reported"}</dd>
              <dt>Source</dt>
              <dd>{data.data?.source ?? "not reported"}</dd>
              <dt>Processed</dt>
              <dd>{data.data?.processed_at ?? "not reported"}</dd>
              <dt>Brightness (display)</dt>
              <dd>
                {current.display_min.toFixed(3)} –{" "}
                {current.display_max.toFixed(3)} {data.display.unit} (
                {data.display.stretch})
              </dd>
              <dt>Expected position</dt>
              <dd>
                {position
                  ? `RA ${position.ra.toFixed(5)} Dec ${position.dec.toFixed(5)} · px (${position.x}, ${position.y})${position.in_image ? "" : " · outside image"}`
                  : "not reported"}
              </dd>
              <dt>Center</dt>
              <dd>
                RA {data.patch.ra.toFixed(5)} Dec {data.patch.dec.toFixed(5)}
              </dd>
              <dt>Corners</dt>
              <dd className={s.mono}>
                {data.sector
                  ? Object.entries(data.sector.corners)
                      .map(
                        ([k, [ra, dec]]) =>
                          `${k} ${ra.toFixed(4)},${dec.toFixed(4)}`,
                      )
                      .join(" · ")
                  : "not reported"}
              </dd>
              <dt>Exposures</dt>
              <dd>
                {current.frames_used} used of {current.frames_available}
              </dd>
            </dl>
          </div>
        </div>
      )}
    </main>
  );
}
