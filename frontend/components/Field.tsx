"use client";
import { useEffect, useState, type ReactNode, type Ref } from "react";
import {
  ArrowLeft,
  ArrowLeftRight,
  ArrowUpDown,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  Layers,
  Pause,
  Play,
  RotateCcw,
} from "lucide-react";
import {
  timeline,
  imageUrl,
  nextEpoch,
  epochDateRange,
  releaseLabel,
  ApiError,
  type Query,
  type Target,
  type Timeline,
  type Building,
} from "@/lib/api";
import { decToParts, raToParts } from "@/lib/coordinates";
import s from "./field.module.css";

const stages: Record<string, string> = {
  queued: "Waiting for a turn",
  querying: "Searching for observations",
  downloading: "Downloading images",
  rendering: "Preparing images",
};
const bands = [
  { range: "0.75–1.09", use: "Stars" },
  { range: "1.10–1.62", use: "Stars and red dwarfs" },
  { range: "1.63–2.41", use: "Variable stars" },
  { range: "2.42–3.82", use: "Stars with dust" },
  { range: "3.83–4.41", use: "Brown dwarfs" },
  { range: "4.42–5.00", use: "Coldest objects" },
];

/** `brown_dwarf_binary` → `Brown dwarf binary`. */
function humanKind(kind: string) {
  const text = kind.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "Catalogued object";
}

/**
 * Observation console: one SPHEREx field, its epochs and the blink comparator,
 * drawn as the holographic screen of the ship (background: console-bg.webp).
 */
export default function Field({
  query,
  target,
  title,
  headingRef,
  onBack,
  recommended,
  speed,
  reduced,
}: {
  query: Query;
  target: Target | null;
  title: string;
  headingRef?: Ref<HTMLHeadingElement>;
  onBack: () => void;
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
  // Preload every epoch before blinking: swapping `src` to an image that is still downloading
  // shows half-loaded frames and makes the loading notice flicker on every step.
  const [loaded, setLoaded] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    setLoaded(new Set());
    const images = data.epochs.map((e) => {
      const url = imageUrl(e.image_url);
      const image = new Image();
      // A failed preload also counts as settled; the visible <img> reports the error.
      image.onload = image.onerror = () => {
        if (!cancelled) setLoaded((done) => new Set(done).add(url));
      };
      image.src = url;
      return image;
    });
    return () => {
      cancelled = true;
      images.forEach((image) => (image.onload = image.onerror = null));
    };
  }, [data, reload]);
  const preloaded = data
    ? data.epochs.filter((e) => loaded.has(imageUrl(e.image_url))).length
    : 0;
  const allPreloaded = !!data && preloaded === data.epochs.length;
  const current = data?.epochs[epoch];
  const currentUrl = current ? imageUrl(current.image_url) : "";
  useEffect(() => {
    setImageError(false);
    setImageLoading(true);
  }, [current?.image_url, reload]);
  const remaining = Math.max(0, Math.ceil((retryAt - now) / 1000));
  const count = data?.epochs.length ?? 0;
  const canCompare = count > 1 && !imageError;

  function stepEpoch(direction: 1 | -1) {
    setPlaying(false);
    setEpoch((e) => (e + direction + count) % count);
  }

  // The patch centre once the API answers; before that, the requested position.
  const center =
    data?.patch ??
    target ??
    (query.ra !== undefined && query.dec !== undefined ? { ra: query.ra, dec: query.dec } : null);
  const ra = center ? raToParts(center.ra) : null;
  const dec = center ? decToParts(center.dec) : null;
  const band = bands[detector - 1];

  return (
    <section className={s.scene} data-console="field" aria-labelledby="field-title">
      <div className={s.stage}>
        <img className={s.room} src="/panels/console-bg.webp" alt="" aria-hidden="true" draggable={false} />
        <div className={s.screen}>
          <svg className={s.frame} viewBox="0 0 1083 678" preserveAspectRatio="none" aria-hidden="true">
            {/* Chamfered outline from the reference; the gap at top-left holds the Back tab. */}
            <path className={s.frameLine} d="M150 0H1030L1083 44V630L1035 678H40L0 636V44L44 0H54" />
            <path className={s.frameRule} d="M0 96H1083" />
          </svg>
          <img className={s.headerArt} src="/panels/console-header.webp" alt="" aria-hidden="true" />

          <button type="button" className={s.back} onClick={onBack}>
            <ArrowLeft aria-hidden="true" /> Back
          </button>
          <header className={s.header}>
            <PlanetIcon />
            <h1 id="field-title" ref={headingRef} tabIndex={-1}>
              {title}
            </h1>
          </header>

          <div className={s.body}>
            <label className={`${s.control} ${s.detector}`}>
              <span>Detector</span>
              <Select value={detector} onChange={(v) => setDetector(Number(v))}>
                {bands.map((b, i) => (
                  <option value={i + 1} key={b.range}>
                    D{i + 1} · {b.range} µm · {b.use}
                  </option>
                ))}
              </Select>
            </label>
            <label className={`${s.control} ${s.size}`}>
              <span>Field size</span>
              <Select value={size} onChange={setSize}>
                <option value="small">3 arcminutes</option>
                <option value="medium">6 arcminutes</option>
                <option value="large">15 arcminutes</option>
              </Select>
            </label>

            <div className={s.viewer}>
              <span className={`${s.compass} ${s.north}`} aria-hidden="true">N ↑</span>
              <span className={`${s.compass} ${s.south}`} aria-hidden="true">S ↓</span>
              <span className={`${s.compass} ${s.east}`} aria-hidden="true">E ←</span>
              <span className={`${s.compass} ${s.west}`} aria-hidden="true">→ W</span>
              <div className={s.image}>
                <span className={s.brackets} aria-hidden="true" />
                {error ? (
                  <div className={s.message} role="alert">
                    <strong>We could not open this field</strong>
                    <p>{error}</p>
                    <button
                      type="button"
                      className={s.retry}
                      disabled={remaining > 0}
                      onClick={() => setReload((x) => x + 1)}
                    >
                      <RotateCcw aria-hidden="true" />
                      {remaining > 0 ? `Retry in ${remaining} s` : "Retry"}
                    </button>
                  </div>
                ) : !data ? (
                  <div className={s.message} role="status">
                    <strong>
                      {progress
                        ? stages[progress.progress.stage] || "Preparing the field"
                        : "Checking images"}
                    </strong>
                    <p>A new field can take a few minutes. You can go back to the menu.</p>
                    {progress && (
                      <>
                        <progress
                          max={progress.progress.total || 1}
                          value={progress.progress.total ? progress.progress.done : undefined}
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
                  <p className={s.message}>
                    This field has no epochs available yet. Try another detector or size.
                  </p>
                ) : imageError ? (
                  <div className={s.message} role="alert">
                    <p>This image could not be loaded.</p>
                    <button type="button" className={s.retry} onClick={() => setReload((n) => n + 1)}>
                      <RotateCcw aria-hidden="true" /> Reload
                    </button>
                  </div>
                ) : (
                  <>
                    <img
                      src={currentUrl}
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
                    {imageLoading && !loaded.has(currentUrl) && (
                      <span role="status" className={s.imageStatus}>
                        Loading epoch…
                      </span>
                    )}
                    {/* The patch centre is the central pixel, which is where the target sits. */}
                    <span className={s.reticle} aria-hidden="true" />
                  </>
                )}
              </div>
            </div>

            <div className={s.cards}>
              <section className={s.card} aria-labelledby="field-coordinates">
                <h2 id="field-coordinates">
                  <Crosshair aria-hidden="true" /> Coordinates (ICRS)
                </h2>
                <dl>
                  <div>
                    <dt>
                      <ArrowLeftRight aria-hidden="true" /> RA
                    </dt>
                    <dd className={s.sexagesimal}>
                      {ra ? (
                        <>
                          {ra.h}<i>h</i> {ra.m}<i>m</i> {ra.s}<i>s</i>
                        </>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>
                      <ArrowUpDown aria-hidden="true" /> Dec
                    </dt>
                    <dd className={s.sexagesimal}>
                      {dec ? (
                        <>
                          {dec.sign === "-" ? "−" : "+"}
                          {dec.d}<i>°</i> {dec.m}<i>′</i> {dec.s}<i>″</i>
                        </>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </div>
                </dl>
              </section>
              <section className={s.card} aria-labelledby="field-object">
                <h2 id="field-object">
                  <Layers aria-hidden="true" /> Object
                </h2>
                <dl>
                  <div>
                    <dt>Name</dt>
                    <dd>{target?.name ?? "Custom position"}</dd>
                  </div>
                  <div>
                    <dt>Type</dt>
                    <dd>{target ? humanKind(target.kind) : "Field chosen by coordinates"}</dd>
                  </div>
                  <div>
                    <dt>Band</dt>
                    <dd>
                      D{detector} · {data ? data.detector.wavelength_range_um.join("–") : band.range} µm
                      {data && ` · ${data.size.pixel_scale_arcsec}″/px`}
                    </dd>
                  </div>
                  <div>
                    <dt>Instrument</dt>
                    {/* The data release comes from the API for the epoch on screen; never hard-coded. */}
                    <dd>{releaseLabel(current?.releases)}</dd>
                  </div>
                </dl>
              </section>
            </div>

            <div className={s.timeline}>
              <p className={s.observed}>
                {current
                  ? `Observed: ${epochDateRange(current.start_utc, current.end_utc)} UTC`
                  : "Observed: —"}
                {count === 1 && " · Only one epoch is available; comparing needs at least two."}
              </p>
              <p className={s.honest}>
                <strong>Observed change.</strong> A change between images does not confirm a new
                object. Transparent areas have no data.
              </p>
              <button
                type="button"
                className={s.compare}
                disabled={!canCompare || !allPreloaded}
                onClick={() => setPlaying((p) => !p)}
              >
                {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
                {playing
                  ? "Pause"
                  : !data || allPreloaded
                    ? "Compare epochs"
                    : `Loading epochs ${preloaded}/${count}`}
              </button>
              <label className={`${s.control} ${s.interval}`}>
                <span>Interval</span>
                <Select value={interval} onChange={(v) => setIntervalMs(Number(v))}>
                  <option value="400">0.4 seconds</option>
                  <option value="800">0.8 seconds</option>
                  <option value="1500">1.5 seconds</option>
                </Select>
              </label>
              <span className={s.counter} aria-live="polite">
                {count ? `Epoch ${epoch + 1} of ${count}` : "Epoch —"}
              </span>
              <div className={s.steps}>
                <button type="button" aria-label="Previous epoch" disabled={!canCompare} onClick={() => stepEpoch(-1)}>
                  <ChevronLeft aria-hidden="true" />
                </button>
                <button type="button" aria-label="Next epoch" disabled={!canCompare} onClick={() => stepEpoch(1)}>
                  <ChevronRight aria-hidden="true" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Select({
  value,
  onChange,
  children,
}: {
  value: string | number;
  onChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <span className={s.select}>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {children}
      </select>
      <ChevronDown aria-hidden="true" />
    </span>
  );
}

/** Ringed planet, as in the reference title. */
function PlanetIcon() {
  return (
    <svg className={s.planet} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="15" />
      <path d="M12.5 44.5C4 50 2 54.5 6 56c6 2.2 22-4.6 36-15.5S62 15.6 58 9.6C56 6.8 50 8 43 12" />
    </svg>
  );
}
