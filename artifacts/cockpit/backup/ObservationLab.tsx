"use client";
// Observation viewer: a full-screen, interactive view of the SPHEREx epochs. The image is the
// interface (zoom, pan, click for coordinates, drag a pin); the controls are compact overlays.
// Deliberately unstyled beyond the basics: the final look is decided by the menu.
import { useEffect, useMemo, useRef, useState } from "react";
import { epochDateRange } from "@/lib/api";
import {
  colorPalettes,
  epochImageUrl,
  loadTargets,
  type ColorPalette,
  type LabTarget,
  type Palette,
  type Source,
} from "@/lib/lab/contract";
import type { SizeName } from "@/lib/lab/fov";
import {
  allImageUrls,
  levelGeometry,
  loadImage,
  loadLevels,
  loadedLevels,
  type LabLevels,
} from "@/lib/lab/levels";
import {
  formatDec,
  formatRa,
  gridFrom,
  skyToPixel,
  type SkyPoint,
} from "@/lib/lab/sky";
import ImageViewport, { type Hover } from "./ImageViewport";
import s from "./lab.module.css";

type Preload = { loaded: number; total: number; ms: number | null };

export default function ObservationLab() {
  // Real SPHEREx data by default. The demo images are synthetic (made-up brightness, noise and
  // dates), so they are only shown when chosen, and always under a visible "simulated" banner.
  const [source, setSource] = useState<Source>("api");
  const [targets, setTargets] = useState<LabTarget[]>([]);
  const [slug, setSlug] = useState("barnards-star");
  const [detector, setDetector] = useState(3);
  // The three field-of-view levels of the selected object, and the one currently shown. The
  // viewer picks the level from the zoom (lib/lab/fov.ts), so there is no size selector.
  const [levels, setLevels] = useState<LabLevels | null>(null);
  const [levelName, setLevelName] = useState<SizeName>("medium");
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
  const [panelOpen, setPanelOpen] = useState(false);
  // The pin is stored as a sky position, so it survives epoch, level and detector changes.
  const [pin, setPin] = useState<SkyPoint | null>(null);
  const [hover, setHover] = useState<Hover>(null);
  const [announce, setAnnounce] = useState("");
  const [copied, setCopied] = useState(false);
  // "infrared" = the raw single band in grey; "color" = the same band painted with a palette.
  const [display, setDisplay] = useState<"infrared" | "color">("infrared");
  const [colorPalette, setColorPalette] = useState<ColorPalette>("inferno");
  // Only the demo export has colour images; the real API returns grey.
  const wanted: Palette =
    source === "demo" && display === "color" ? colorPalette : "gray";
  const wantedRef = useRef(wanted);
  wantedRef.current = wanted;
  const selectionKey = `${source}|${slug}|${detector}`;
  // Which selection `levels` was loaded for. During a source/object/detector change `levels` is
  // briefly the previous selection's, and the palette swap below must not act on it.
  const [loadedKey, setLoadedKey] = useState("");
  // False for the one render where `source` already changed but `levels` is still the previous
  // source's: building image URLs then mixes the two (e.g. /lab/demo/api/v1/images/4.png).
  const fresh = loadedKey === selectionKey;
  const ready = preload.total > 0 && preload.loaded === preload.total;
  // The timeline of the level on screen; the others are only needed for the viewer's ladder.
  const data = useMemo(
    () => levels?.[levelName] ?? loadedLevels(levels ?? {})[0] ?? null,
    [levels, levelName],
  );

  useEffect(() => {
    const abort = new AbortController();
    setError("");
    loadTargets(source)
      .then((t) => !abort.signal.aborted && setTargets(t))
      .catch((e: Error) => !abort.signal.aborted && setError(e.message));
    return () => abort.abort();
  }, [source]);

  // Every selection change requests the levels again and resets playback.
  useEffect(() => {
    const abort = new AbortController();
    setLevels(null);
    setLevelName("medium");
    setError("");
    setStatus("Loading…");
    setEpoch(0);
    setPlaying(false);
    setImageError(false);
    setHover(null);
    setPreload({ loaded: 0, total: 0, ms: null });
    loadLevels(
      source,
      slug,
      detector,
      wantedRef.current,
      abort.signal,
      (stage, done, total) => setStatus(`Building: ${stage} ${done}/${total}`),
    )
      .then((l) => {
        if (abort.signal.aborted) return;
        setLevels(l);
        setLoadedKey(selectionKey);
        setStatus("");
      })
      .catch((e: Error) => {
        if (abort.signal.aborted) return;
        setError(e.message);
        setStatus("");
      });
    return () => abort.abort();
  }, [source, slug, detector]);

  // Switching between infrared and colour swaps the image sets in place: the epochs, positions
  // and pixels are identical (checked in tests/demo-palettes.test.ts), only the painting
  // differs. The new sets are downloaded first and swapped in one go, so there is no flash and
  // the zoom, pan, pin, epoch and level are all kept. `levels` is deliberately not reset, which
  // keeps the viewer's resetKey (and therefore its view) unchanged.
  const shownPalette = data?.palette;
  useEffect(() => {
    if (!levels || loadedKey !== selectionKey || shownPalette === wanted)
      return;
    const abort = new AbortController();
    loadLevels(source, slug, detector, wanted, abort.signal)
      .then(async (next) => {
        await Promise.all(allImageUrls(source, next).map(loadImage));
        if (abort.signal.aborted) return;
        setLevels(next);
        setEpoch((i) =>
          Math.min(i, (loadedLevels(next)[0]?.epochs.length ?? 1) - 1),
        );
      })
      .catch((e: Error) => {
        if (abort.signal.aborted) return;
        setError(e.message);
        setDisplay("infrared");
      });
    return () => abort.abort();
  }, [
    levels,
    shownPalette,
    loadedKey,
    selectionKey,
    wanted,
    source,
    slug,
    detector,
  ]);

  // Preload every epoch of every level, so neither blinking nor changing level ever waits for
  // the network. The time is shown to learn whether a strip of images should be requested from
  // the backend.
  useEffect(() => {
    if (!levels || !fresh) return;
    let cancelled = false;
    const started = performance.now();
    const urls = allImageUrls(source, levels);
    const total = urls.length;
    setPreload({ loaded: 0, total, ms: null });
    let loaded = 0;
    const done = () => {
      if (cancelled) return;
      loaded += 1;
      setPreload({
        loaded,
        total,
        ms: loaded === total ? Math.round(performance.now() - started) : null,
      });
    };
    urls.forEach((url) =>
      loadImage(url).then(done, () => {
        if (cancelled) return;
        setImageError(true);
        done();
      }),
    );
    return () => {
      cancelled = true;
    };
  }, [levels, source, fresh]);

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
  // `grid` is the sky grid of the level on screen (pixel readouts); `worldGrid` is the largest
  // level's, the space the viewer works in.
  const grid = useMemo(() => (data ? gridFrom(data) : null), [data]);
  const worldGrid = useMemo(() => {
    const all = loadedLevels(levels ?? {});
    return all.length ? gridFrom(all[all.length - 1]) : null;
  }, [levels]);
  const viewerLevels = useMemo(() => levelGeometry(levels ?? {}), [levels]);
  const activeLevel = (data?.size.name ?? levelName) as SizeName;
  const releases = useMemo(
    () => [...new Set(data?.epochs.flatMap((e) => e.releases ?? []))],
    [data],
  );
  const position = current?.expected_position;
  const markerPx =
    marker && position?.in_image ? { x: position.x, y: position.y } : null;

  // Pin position in the current image, for the readout. null = the pin is outside this image.
  const pinPx = useMemo(() => {
    if (!pin || !grid) return null;
    const p = skyToPixel(grid, pin.ra, pin.dec);
    const inside =
      p.x >= -0.5 &&
      p.y >= -0.5 &&
      p.x <= grid.width - 0.5 &&
      p.y <= grid.height - 0.5;
    return inside ? p : null;
  }, [pin, grid]);

  function handlePin(next: SkyPoint | null, final: boolean) {
    setPin(next);
    setCopied(false);
    // Announce only settled positions; during a drag the screen reader would be flooded.
    if (final) {
      setAnnounce(
        next
          ? `Pin at RA ${formatRa(next.ra)}, Dec ${formatDec(next.dec)}`
          : "Pin removed",
      );
    }
  }

  function showDisplay(next: "infrared" | "color") {
    if (source !== "demo") return;
    setDisplay(next);
    setAnnounce(
      next === "color"
        ? `Showing the ${colorPalette} color palette`
        : "Showing the infrared band in grey",
    );
  }
  // Based on what is actually shown (`wanted`), not on the last choice: with the real API the
  // image is always grey, whatever was picked before.
  const toggleDisplay = () =>
    showDisplay(wanted === "gray" ? "color" : "infrared");

  async function copyPin() {
    if (!pin) return;
    try {
      await navigator.clipboard.writeText(
        `${pin.ra.toFixed(6)} ${pin.dec.toFixed(6)}`,
      );
      setCopied(true);
    } catch {
      // Clipboard can be blocked (insecure context, permissions); the coordinates stay visible.
      setCopied(false);
    }
  }

  return (
    <main className={s.lab}>
      {fresh && data && current && grid && worldGrid && (
        <ImageViewport
          src={epochImageUrl(source, current, data.palette)}
          alt={`Epoch ${epoch + 1} of ${count}, ${current.start_utc.slice(0, 10)}`}
          grid={worldGrid}
          levels={viewerLevels}
          levelName={activeLevel}
          startLevel="medium"
          onLevelChange={setLevelName}
          resetKey={selectionKey}
          marker={markerPx}
          pin={pin}
          onPinChange={handlePin}
          onHover={setHover}
          onImageError={() => setImageError(true)}
          onToggleDisplay={toggleDisplay}
        />
      )}

      <header className={s.top}>
        <a href="/" className={s.back} aria-label="Back to the menu">
          ← <span className={s.backText}>Back to the menu</span>
        </a>
        <h1 className={s.title}>Observation lab</h1>
        {source === "demo" && (
          <p className={s.simulated} role="note">
            Simulated data · not real SPHEREx observations
          </p>
        )}
        <div
          className={s.segment}
          role="group"
          aria-label="Image display"
          title={
            source === "demo"
              ? "Press C on the image to switch"
              : "Color images are only available in the demo data for now"
          }
        >
          <button
            type="button"
            aria-pressed={wanted === "gray"}
            onClick={() => showDisplay("infrared")}
          >
            Infrared band
          </button>
          <button
            type="button"
            aria-pressed={wanted !== "gray"}
            disabled={source !== "demo"}
            onClick={() => showDisplay("color")}
          >
            Color
          </button>
        </div>
        <button
          type="button"
          className={s.panelButton}
          aria-expanded={panelOpen}
          aria-controls="viewer-panel"
          onClick={() => setPanelOpen((o) => !o)}
        >
          Controls
        </button>
      </header>

      {panelOpen && (
        <aside
          id="viewer-panel"
          className={s.panel}
          aria-label="Viewer controls and image details"
        >
          <div className={s.controls}>
            <label>
              Source
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as Source)}
              >
                <option value="api">Real SPHEREx data</option>
                <option value="demo">Simulated demo (not real data)</option>
              </select>
            </label>
            <label>
              Object
              <select value={slug} onChange={(e) => setSlug(e.target.value)}>
                {(targets.length ? targets : [{ slug, name: slug }]).map(
                  (t) => (
                    <option key={t.slug} value={t.slug}>
                      {t.name}
                    </option>
                  ),
                )}
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
              Color palette
              <select
                value={colorPalette}
                disabled={source !== "demo"}
                onChange={(e) =>
                  setColorPalette(e.target.value as ColorPalette)
                }
              >
                {colorPalettes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className={s.check}>
              <input
                type="checkbox"
                checked={marker}
                onChange={(e) => setMarker(e.target.checked)}
              />
              Expected position
            </label>
          </div>
          {data && current && (
            <dl className={s.meta}>
              <dt>Orientation</dt>
              <dd>North up · East left</dd>
              <dt>Image</dt>
              <dd>
                {data.size.side_arcmin}′ · {data.size.width_px}×
                {data.size.height_px}px · chosen by the zoom
              </dd>
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
          )}
        </aside>
      )}

      {(status || error) && (
        <div className={s.message}>
          {status && <p role="status">{status}</p>}
          {error && (
            <>
              <p role="alert">{error}</p>
              {source === "api" && (
                <button type="button" onClick={() => setSource("demo")}>
                  Show the simulated demo instead
                </button>
              )}
            </>
          )}
        </div>
      )}
      {imageError && (
        <div className={s.message}>
          <p role="alert">This epoch&apos;s image could not be loaded.</p>
        </div>
      )}

      {data && current && grid && (
        <>
          <p className={s.sr} role="status" aria-live="polite">
            {announce}
          </p>
          <div className={s.dock}>
            <p className={s.note}>
              {data.palette === "gray"
                ? `Infrared band D${data.detector.id} · ${data.detector.wavelength_range_um.join("–")} µm · grey = brightness`
                : `${data.palette[0].toUpperCase()}${data.palette.slice(1)} palette on infrared band D${data.detector.id} · ${data.detector.wavelength_range_um.join("–")} µm · not the sky's real colors`}
            </p>
            <aside className={s.readout} aria-label="Coordinates">
              {(hover || !pin) && (
                <p className={s.mono}>
                  {hover
                    ? `Cursor  RA ${hover.sky.ra.toFixed(5)}°  Dec ${hover.sky.dec.toFixed(5)}°  · px ${hover.px.x.toFixed(1)}, ${hover.px.y.toFixed(1)}`
                    : "Click or tap the image to drop a coordinate pin."}
                </p>
              )}
              {pin && (
                <div className={s.pinInfo}>
                  <p className={s.mono}>
                    <strong>Pin</strong> RA {pin.ra.toFixed(6)}° · Dec{" "}
                    {pin.dec.toFixed(6)}°
                  </p>
                  <p className={s.mono}>
                    {formatRa(pin.ra)} · {formatDec(pin.dec)} ·{" "}
                    <span>
                      {pinPx
                        ? `px ${pinPx.x.toFixed(1)}, ${pinPx.y.toFixed(1)}`
                        : "outside this image (kept for the next one)"}
                    </span>
                  </p>
                  <div className={s.row}>
                    <button type="button" onClick={copyPin}>
                      {copied ? "Copied" : "Copy"}
                    </button>
                    <button type="button" onClick={() => handlePin(null, true)}>
                      Clear pin
                    </button>
                  </div>
                </div>
              )}
            </aside>
            <footer className={s.bottom}>
              <label className={s.epoch}>
                Epoch {epoch + 1} of {count} ·{" "}
                {epochDateRange(current.start_utc, current.end_utc)} UTC
                {source === "demo" && " · simulated"}
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
              <button
                type="button"
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
            </footer>
          </div>
        </>
      )}
    </main>
  );
}
