"use client";
import { Component, useEffect, useRef, useState, type PointerEvent, type ReactNode, type Ref } from "react";
import {
  ArrowLeft,
  ArrowLeftRight,
  ArrowUpDown,
  Contrast,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  Layers,
  Link2,
  Pause,
  Play,
  RotateCcw,
  Square,
  X,
  Microscope,
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
import { fieldLink } from "@/lib/fieldLink";
import { decToParts, raToParts } from "@/lib/coordinates";
import { pixelToSky } from "@/lib/lab/sky";
import dynamic from "next/dynamic";
import ConsoleSelect from "./ConsoleSelect";
import EpochDiffTriplet from "./science/EpochDiffTriplet";
import ModelsAndMetricsPanel from "./science/ModelsAndMetricsPanel";
import RgbCompositeView from "./science/RgbCompositeView";
import SpectrumChart from "./science/SpectrumChart";
import sci from "./science/science.module.css";
import s from "./field.module.css";

// WebGL only exists in the browser: the wall tablet's 3D model is loaded on the client.
const StarHologram = dynamic(() => import("./StarHologram"), { ssr: false });

const stages: Record<string, string> = {
  queued: "Waiting for a turn",
  first_light: "First images ready",
  preview_ready: "Preview ready",
  refining: "Adding more frames",
  waiting_for_archive: "NASA's archive is busy, retrying automatically",
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
  target: chosen,
  catalog = [],
  title,
  headingRef,
  onBack,
  recommended,
  speed,
  reduced,
  powered = true,
  initialSize = "medium",
  initialEpoch = 0,
}: {
  query: Query;
  target: Target | null;
  /** Catalogue, to name a field opened by coordinates that lands on a catalogued object. */
  catalog?: Target[];
  title: string;
  headingRef?: Ref<HTMLHeadingElement>;
  onBack: () => void;
  recommended: number;
  speed: number;
  reduced: boolean;
  /**
   * Whether the analysis screen is switched on. The page turns it off while the camera
   * turns towards or away from it; switching it on plays the boot sequence.
   */
  powered?: boolean;
  /** Field size and epoch index to open first (from a shared link). */
  initialSize?: string;
  initialEpoch?: number;
}) {
  const [detector, setDetector] = useState(recommended),
    [size, setSize] = useState(initialSize),
    [data, setData] = useState<Timeline | null>(null),
    [progress, setProgress] = useState<Building | null>(null),
    [error, setError] = useState(""),
    [retryAt, setRetryAt] = useState(0),
    [now, setNow] = useState(Date.now()),
    [autoRetry, setAutoRetry] = useState(false),
    // The visitor stopped waiting for this field (the server keeps building it).
    [stopped, setStopped] = useState(false),
    [reload, setReload] = useState(0),
    [epoch, setEpoch] = useState(0),
    [playing, setPlaying] = useState(false),
    [interval, setIntervalMs] = useState(speed),
    [imageError, setImageError] = useState(false),
    [imageLoading, setImageLoading] = useState(true),
    [scienceTab, setScienceTab] = useState<"diff" | "rgb" | "spectrum" | "models">("diff"),
    // Science side panel; "closing" keeps it mounted while it slides out.
    [analysis, setAnalysis] = useState<"closed" | "open" | "closing">("closed"),
    [copied, setCopied] = useState(false);
  // A shared link's epoch applies to the first finished timeline only.
  const firstEpoch = useRef(initialEpoch);
  const analysisButton = useRef<HTMLButtonElement>(null),
    analysisHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    setDetector(recommended);
  }, [recommended]);
  useEffect(() => {
    setIntervalMs(speed);
  }, [speed]);
  const polling = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    polling.current = abort;
    setStopped(false);
    setAnalysis("closed");
    setData(null);
    setProgress(null);
    setError("");
    setPlaying(false);
    setEpoch(0);
    setRetryAt(0);
    setAutoRetry(false);
    buildStart.current = 0;
    timeline(query, size, detector, abort.signal, (b) => {
      setProgress(b);
      // Show the partial epochs as soon as they exist; only swap when the images changed.
      if (b.epochs?.length)
        setData((prev) =>
          prev && prev.epochs.map((e) => e.image_url).join() === b.epochs!.map((e) => e.image_url).join()
            ? prev
            : ({ ...b, status: "ready" } as unknown as Timeline),
        );
    })
      .then((d) => {
        if (!abort.signal.aborted) {
          setData(d);
          setProgress(null);
          // Applied on the finished timeline: partial epochs while building would clamp it.
          if (firstEpoch.current) setEpoch(Math.min(firstEpoch.current, d.epochs.length - 1));
          firstEpoch.current = 0;
        }
      })
      .catch((e: unknown) => {
        if (!abort.signal.aborted) {
          setError(
            e instanceof Error
              ? e.message
              : "The service response could not be read.",
          );
          // An IRSA outage is retried for the visitor; other failures wait for a click.
          setAutoRetry(e instanceof ApiError && e.code === "archive_unavailable");
          if (e instanceof ApiError)
            setRetryAt(
              Date.now() +
                Math.max(e.retryAfter, e.status === 502 ? 60 : 0) * 1000,
            );
        }
      });
    return () => abort.abort();
  }, [query, size, detector, reload]);
  // Clock for the "Elapsed" readout while a new field is being built.
  const buildStart = useRef(0);
  useEffect(() => {
    if (!progress) return;
    if (!buildStart.current) buildStart.current = Date.now();
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [!!progress]);
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
  const [cursor, setCursor] = useState<{ ra: number; dec: number; x: number; y: number } | null>(null);
  const [difference, setDifference] = useState(false);
  const [pixels, setPixels] = useState<{ w: number; h: number } | null>(null);
  const [phase, setPhase] = useState<"off" | "boot" | "on" | "shutdown">(() =>
    powered ? (reduced ? "on" : "boot") : "off",
  );
  useEffect(() => {
    if (powered) {
      if (reduced) return setPhase("on");
      setPhase("boot");
      // Matches the boot animation in field.module.css (CRT line + initialising log).
      const id = setTimeout(() => setPhase("on"), 1700);
      return () => clearTimeout(id);
    }
    setPhase((p) => (p === "off" ? "off" : "shutdown"));
    const id = setTimeout(() => setPhase("off"), 320);
    return () => clearTimeout(id);
  }, [powered, reduced]);
  const remaining = Math.max(0, Math.ceil((retryAt - now) / 1000));
  function closeAnalysis() {
    analysisButton.current?.focus();
    setAnalysis(reduced ? "closed" : "closing");
  }
  // Esc closes the panel wherever the focus is (it is not modal: the image stays usable).
  useEffect(() => {
    if (analysis !== "open") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAnalysis();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [analysis]);
  useEffect(() => {
    if (analysis === "open") analysisHeading.current?.focus();
    if (analysis !== "closing") return;
    // Matches the 280 ms slide-out in science.module.css.
    const id = setTimeout(() => setAnalysis("closed"), 280);
    return () => clearTimeout(id);
  }, [analysis]);
  /** Stop waiting: polling ends here; the backend build is not cancelled and is cached. */
  function stopWaiting() {
    polling.current?.abort();
    setProgress(null);
    setData(null);
    setPlaying(false);
    setError("");
    setAutoRetry(false);
    setStopped(true);
  }
  useEffect(() => {
    if (error && autoRetry && retryAt && now >= retryAt) setReload((n) => n + 1);
  }, [error, autoRetry, retryAt, now]);
  const count = data?.epochs.length ?? 0;
  // A refined timeline can have a different number of epochs than its preview.
  useEffect(() => {
    if (count && epoch >= count) setEpoch(count - 1);
  }, [count, epoch]);
  // Epochs are compared only once every image is downloaded; partial ones are a preview.
  const building = !!progress;
  const canCompare = count > 1 && !imageError && !building;
  const elapsed = buildStart.current ? Math.max(0, Math.floor((now - buildStart.current) / 1000)) : 0;

  function stepEpoch(direction: 1 | -1) {
    setPlaying(false);
    setEpoch((e) => (e + direction + count) % count);
  }

  /** Sky position under the pointer: the image is the patch, one pixel = pixel_scale_arcsec. */
  function readCursor(e: PointerEvent<HTMLDivElement>) {
    const img = e.currentTarget.querySelector<HTMLImageElement>("img[data-epoch]");
    if (!data || !pixels || !img) return;
    const r = img.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * pixels.w);
    const y = Math.floor(((e.clientY - r.top) / r.height) * pixels.h);
    if (x < 0 || y < 0 || x >= pixels.w || y >= pixels.h) return setCursor(null);
    const sky = pixelToSky(
      { ra: data.patch.ra, dec: data.patch.dec, width: pixels.w, height: pixels.h, scaleArcsec: data.size.pixel_scale_arcsec },
      x,
      y,
    );
    setCursor({ ...sky, x, y });
  }
  const reference = data?.epochs[0];
  const showDifference = difference && !!reference && epoch > 0;

  // Coordinates within the patch-reuse radius of a catalogued object get that object's patch.
  const target = chosen ?? catalog.find((t) => t.slug === data?.patch.target) ?? null;
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
        {/* The wall tablet shows the observed object as a spinning 3D model (an illustration). */}
        <StarHologram target={target} reduced={reduced} />
        <div className={s.screen} data-phase={phase}>
          <svg className={s.frame} viewBox="0 0 1083 678" preserveAspectRatio="none" aria-hidden="true">
            {/* Chamfered outline from the reference; the gap at top-left holds the Back tab. */}
            <path className={s.frameLine} d="M150 0H1030L1083 44V630L1035 678H40L0 636V44L44 0H54" />
            <path className={s.frameRule} d="M0 96H1083" />
          </svg>
          <img className={s.headerArt} src="/panels/console-header.webp" alt="" aria-hidden="true" />
          {phase === "boot" && (
            <BootLog
              name={target?.name ?? title}
              band={`D${detector} · ${band.range} µm`}
              status={
                error ? "service unavailable" : data ? `${count} epoch${count === 1 ? "" : "s"} ready` : "fetching…"
              }
            />
          )}

          <button type="button" className={s.back} onClick={onBack}>
            <ArrowLeft aria-hidden="true" /> Back
          </button>
          <header className={s.header}>
            <PlanetIcon />
            <h1 id="field-title" ref={headingRef} tabIndex={-1}>
              {target?.name ?? title}
            </h1>
            <button
              type="button"
              className={s.copyLink}
              onClick={async () => {
                const url = fieldLink(location.origin + location.pathname, query, size, detector, epoch);
                try {
                  await navigator.clipboard.writeText(url);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                } catch {
                  /* Clipboard blocked (insecure context): show the link so it can be copied by hand. */
                  prompt("Copy this link", url);
                }
              }}
            >
              <Link2 aria-hidden="true" /> <span aria-live="polite">{copied ? "Copied" : "Copy link"}</span>
            </button>
          </header>

          <div className={s.body}>
            <ConsoleSelect
              className={s.detector}
              label="Detector"
              value={String(detector)}
              onChange={(v) => setDetector(Number(v))}
              options={bands.map((b, i) => ({ value: String(i + 1), label: `D${i + 1} · ${b.range} µm · ${b.use}` }))}
            />
            <ConsoleSelect
              className={s.size}
              label="Field size"
              value={size}
              onChange={setSize}
              options={[
                { value: "small", label: "3 arcminutes" },
                { value: "medium", label: "6 arcminutes" },
                { value: "large", label: "15 arcminutes" },
              ]}
            />

            <div className={s.viewer}>
              <span className={`${s.compass} ${s.north}`} aria-hidden="true">N ↑</span>
              <span className={`${s.compass} ${s.south}`} aria-hidden="true">S ↓</span>
              <span className={`${s.compass} ${s.east}`} aria-hidden="true">E ←</span>
              <span className={`${s.compass} ${s.west}`} aria-hidden="true">→ W</span>
              <div
                className={s.image}
                tabIndex={current ? 0 : -1}
                aria-label={current ? "Field image. Left and right arrows change the epoch." : undefined}
                onPointerMove={readCursor}
                onPointerLeave={() => setCursor(null)}
                onKeyDown={(e) => {
                  if (!canCompare) return;
                  if (e.key === "ArrowRight") stepEpoch(1);
                  else if (e.key === "ArrowLeft") stepEpoch(-1);
                  else return;
                  e.preventDefault();
                }}
              >
                <span className={s.brackets} aria-hidden="true" />
                {stopped ? (
                  <div className={s.message} role="status">
                    <strong>Stopped</strong>
                    <p>
                      Nebo stopped waiting for this field. Its server keeps preparing the images in the
                      background, so opening it again later can be much faster.
                    </p>
                    <button type="button" className={s.retry} onClick={() => setReload((x) => x + 1)}>
                      <RotateCcw aria-hidden="true" /> Try again
                    </button>
                  </div>
                ) : error ? (
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
                      {remaining > 0
                        ? autoRetry
                          ? `Retrying automatically in ${remaining} s`
                          : `Retry in ${remaining} s`
                        : "Retry"}
                    </button>
                    {autoRetry && remaining > 0 && (
                      <button type="button" className={s.stop} onClick={stopWaiting}>
                        <Square aria-hidden="true" /> Stop retrying
                      </button>
                    )}
                  </div>
                ) : !data ? (
                  <div className={s.message} role="status">
                    <strong>Fetching real SPHEREx images</strong>
                    <p>
                      Nebo asks NASA/IPAC IRSA for every SPHEREx exposure of this point, downloads them and
                      stacks them into one image per epoch. A new field usually takes 1–3 minutes; after that
                      it opens instantly. You can go back to the menu meanwhile.
                    </p>
                    <BuildSteps progress={progress} />
                    {progress?.progress.stage === "waiting_for_archive" && (
                      <p className={s.reassure}>
                        This is normal: NASA&apos;s archive is very busy at times and can need 2, 3 or even 4
                        attempts. Nebo keeps trying on its own for up to 5 minutes; you don&apos;t need to do
                        anything.
                      </p>
                    )}
                    <BuildBar progress={progress} />
                    {progress && <p className={s.elapsed}>Elapsed {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</p>}
                    {progress && (
                      <button type="button" className={s.stop} onClick={stopWaiting}>
                        <Square aria-hidden="true" /> Stop
                      </button>
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
                    {/*
                      * Difference view: the current epoch is blended over the first one with
                      * `difference`, so unchanged sky goes black and only brightness changes glow.
                      * All epochs of a field share one display scale, so the subtraction is fair.
                      */}
                    {showDifference && (
                      <img className={s.reference} src={imageUrl(reference.image_url)} alt="" aria-hidden="true" />
                    )}
                    <img
                      data-epoch
                      className={showDifference ? s.differenceLayer : undefined}
                      src={currentUrl}
                      alt={`Infrared image of the field observed on ${current.start_utc.slice(0, 10)}, detector ${detector}${showDifference ? ", shown as the difference from the first epoch" : ""}`}
                      width={420}
                      height={420}
                      onLoad={(e) => {
                        setImageLoading(false);
                        setPixels({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight });
                      }}
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
                    {building && <span className={s.previewTag}>Preview</span>}
                    {!building && data?.patch.id && (
                      <button
                        ref={analysisButton}
                        type="button"
                        className={`${s.diffToggle} ${s.analysisToggle}`}
                        aria-expanded={analysis === "open"}
                        aria-controls="science-panel"
                        title="Open the scientific analysis panel"
                        onClick={() => (analysis === "open" ? closeAnalysis() : setAnalysis("open"))}
                      >
                        <Microscope aria-hidden="true" /> Analysis
                      </button>
                    )}
                    {/* The patch centre is the central pixel, which is where the target sits. */}
                    <span className={s.reticle} aria-hidden="true" />
                    <button
                      type="button"
                      className={s.diffToggle}
                      aria-pressed={difference}
                      disabled={!canCompare}
                      title="Show what changed since the first epoch"
                      onClick={() => setDifference((d) => !d)}
                    >
                      <Contrast aria-hidden="true" /> Difference
                    </button>
                    <p className={s.readout} aria-live="off">
                      {cursor
                        ? `x ${cursor.x}, y ${cursor.y} · RA ${cursor.ra.toFixed(4)}° · Dec ${cursor.dec >= 0 ? "+" : "−"}${Math.abs(cursor.dec).toFixed(4)}°`
                        : difference
                          ? epoch === 0
                            ? "Epoch 1 is the reference: step to another epoch"
                            : "Difference from epoch 1 · bright = changed"
                          : "Hover the image to read a position"}
                    </p>
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
                {count === 1 && !building && (
                  <span className={s.oneEpoch}>Only one epoch is available; comparing needs at least two.</span>
                )}
              </p>
              {building && data ? (
                <div className={`${s.honest} ${s.buildStatus}`} role="status">
                  <p>
                    <strong>Still downloading images</strong>
                    {progress!.progress.total > 0 &&
                      ` · ${progress!.progress.done} of ${progress!.progress.total} exposures`}
                    . You can look at the preview; comparing epochs unlocks when every image is ready.
                  </p>
                  <BuildBar progress={progress} />
                  <button type="button" className={s.stop} onClick={stopWaiting}>
                    <Square aria-hidden="true" /> Stop loading
                  </button>
                </div>
              ) : (
                <p className={s.honest}>
                  <strong>Observed change.</strong> A change between images does not confirm a new
                  object. Transparent areas have no data.
                </p>
              )}
              <button
                type="button"
                className={s.compare}
                disabled={!canCompare || !allPreloaded}
                onClick={() => setPlaying((p) => !p)}
              >
                {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
                {playing
                  ? "Pause"
                  : building && data
                    ? "Downloading…"
                    : !data || allPreloaded
                    ? "Compare epochs"
                    : `Loading epochs ${preloaded}/${count}`}
              </button>
              <ConsoleSelect
                className={s.interval}
                label="Interval"
                value={String(interval)}
                onChange={(v) => setIntervalMs(Number(v))}
                options={[
                  { value: "400", label: "0.4 seconds" },
                  { value: "800", label: "0.8 seconds" },
                  { value: "1500", label: "1.5 seconds" },
                ]}
              />
              <div className={s.counter}>
                <span aria-live="polite">{count ? `Epoch ${epoch + 1} of ${count}` : "Epoch —"}</span>
                {count > 1 && (
                  // One mark per epoch, spaced by date, so the gaps between visits are visible.
                  <EpochStrip
                    epochs={data!.epochs}
                    current={epoch}
                    onPick={(i) => {
                      if (building) return;
                      setPlaying(false);
                      setEpoch(i);
                    }}
                  />
                )}
              </div>
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
            {data?.patch.id && !building && analysis !== "closed" && (
              <aside
                id="science-panel"
                className={sci.drawer}
                data-state={analysis}
                role="dialog"
                aria-labelledby="science-panel-title"
              >
                <header className={sci.drawerHeader}>
                  <h2 id="science-panel-title" ref={analysisHeading} tabIndex={-1}>
                    <Microscope aria-hidden="true" /> Scientific analysis
                  </h2>
                  <button type="button" className={sci.drawerClose} aria-label="Close scientific analysis" onClick={closeAnalysis}>
                    <X aria-hidden="true" />
                  </button>
                </header>
                <div className={sci.drawerBody}>
                <div className={sci.tabs} role="tablist" aria-label="Scientific analysis filters">
                  {(
                    [
                      ["diff", "Compare (3-Panel)"],
                      ["rgb", "RGB Composite"],
                      ["spectrum", "Spectrum (102 ch)"],
                      ["models", "Models & Metrics"],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      role="tab"
                      aria-selected={scienceTab === id}
                      className={sci.tab}
                      onClick={() => setScienceTab(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {/* Keyed by tab: a crash in one analysis resets when another tab is chosen. */}
                <AnalysisBoundary key={scienceTab}>
                {scienceTab === "diff" && (
                  <EpochDiffTriplet
                    patchId={data.patch.id}
                    query={query}
                    detector={detector}
                    size={size}
                    epochs={data.epochs}
                    currentEpoch={epoch}
                    widthPx={data.size.width_px ?? pixels?.w}
                    heightPx={data.size.height_px ?? pixels?.h}
                  />
                )}
                {scienceTab === "rgb" && (
                  <RgbCompositeView
                    patchId={data.patch.id}
                    query={query}
                    size={size}
                    epoch={epoch}
                    onBuildDetector={(d) => setDetector(d)}
                  />
                )}
                {scienceTab === "spectrum" && <SpectrumChart patchId={data.patch.id} />}
                {scienceTab === "models" && (
                  <ModelsAndMetricsPanel
                    patchId={data.patch.id}
                    detector={detector}
                    epochIndex={epoch}
                  />
                )}
                </AnalysisBoundary>
                </div>
              </aside>
            )}
        </div>
      </div>
    </section>
  );
}

/** One analysis that fails to render shows a note instead of taking the whole page down. */
class AnalysisBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error("Scientific analysis failed to render", error);
  }
  render() {
    return this.state.failed ? (
      <p className={s.message} role="alert">
        This analysis could not be shown for this field. The other tabs still work.
      </p>
    ) : (
      this.props.children
    );
  }
}

// The backend build stages, grouped into the steps a visitor can follow.
const buildSteps: { label: string; stages: string[] }[] = [
  { label: "Search the SPHEREx archive (IRSA)", stages: ["queued", "querying", "waiting_for_archive"] },
  { label: "Download the exposures", stages: ["downloading"] },
  { label: "First image", stages: ["first_light"] },
  { label: "One image per epoch", stages: ["preview_ready"] },
  { label: "Add more exposures for a sharper image", stages: ["refining", "rendering"] },
];

function BuildSteps({ progress }: { progress: Building | null }) {
  const stage = progress?.progress.stage ?? "queued";
  const current = Math.max(0, buildSteps.findIndex((step) => step.stages.includes(stage)));
  const { done, total } = progress?.progress ?? { done: 0, total: 0 };
  return (
    <ol className={s.buildSteps}>
      {buildSteps.map((step, i) => (
        <li key={step.label} data-state={i < current ? "done" : i === current ? "current" : "pending"} aria-current={i === current ? "step" : undefined}>
          <span aria-hidden="true">{i < current ? "✓" : i === current ? "●" : "○"}</span>
          {step.label}
          {i === current && i === 1 && total > 0 && ` · ${done} of ${total}`}
          {i === current && stage === "waiting_for_archive" &&
            ` · NASA's archive is busy, retrying automatically (attempt ${done})`}
        </li>
      ))}
    </ol>
  );
}

/** Determinate once the number of exposures is known; a moving stripe before that. */
function BuildBar({ progress }: { progress: Building | null }) {
  const total = progress?.progress.total ?? 0;
  return (
    <progress
      className={s.buildBar}
      max={total || 1}
      value={total ? progress!.progress.done : undefined}
      aria-label="Field preparation"
    />
  );
}

/**
 * What the analysis screen prints while it powers up. Every line states something real
 * (target, band, what the archive answered), so the wait is informative, not decoration.
 */
function BootLog({ name, band, status }: { name: string; band: string; status: string }) {
  return (
    <div className={s.boot} role="status" aria-label="Initialising the analysis console">
      <p className={s.bootTitle}>Nebo · analysis console</p>
      <ol>
        <li>Initialising display…</li>
        <li>Linking SPHEREx archive…</li>
        <li>Target: {name}</li>
        <li>Detector {band}</li>
        <li>Epochs: {status}</li>
      </ol>
      <span className={s.bootBar} aria-hidden="true">
        <i />
      </span>
    </div>
  );
}

/** Clickable timeline of the epochs, placed by observation date. */
function EpochStrip({
  epochs,
  current,
  onPick,
}: {
  epochs: { start_utc: string; end_utc: string }[];
  current: number;
  onPick: (i: number) => void;
}) {
  const times = epochs.map((e) => new Date(e.start_utc).getTime());
  const first = Math.min(...times);
  const span = Math.max(1, Math.max(...times) - first);
  return (
    <div className={s.strip} role="group" aria-label="Epochs by date">
      <span className={s.stripLine} aria-hidden="true" />
      {epochs.map((e, i) => (
        <button
          key={e.start_utc + i}
          type="button"
          style={{ left: `${((times[i] - first) / span) * 100}%` }}
          aria-label={`Epoch ${i + 1}: ${epochDateRange(e.start_utc, e.end_utc)}`}
          aria-current={i === current}
          title={epochDateRange(e.start_utc, e.end_utc)}
          onClick={() => onPick(i)}
        />
      ))}
    </div>
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
