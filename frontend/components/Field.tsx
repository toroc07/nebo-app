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
  queued: "Esperando turno",
  querying: "Buscando observaciones",
  downloading: "Descargando imágenes",
  rendering: "Preparando imágenes",
};
const bands = [
  "0,75–1,09 · Estrellas",
  "1,10–1,62 · Estrellas y enanas rojas",
  "1,63–2,41 · Estrellas variables",
  "2,42–3,82 · Estrellas con polvo",
  "3,83–4,41 · Enanas marrones",
  "4,42–5,00 · Objetos más fríos",
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
              : "No se pudo leer la respuesta del servicio.",
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
          Tamaño del campo
          <select value={size} onChange={(e) => setSize(e.target.value)}>
            <option value="small">3 minutos de arco</option>
            <option value="medium">6 minutos de arco</option>
            <option value="large">15 minutos de arco</option>
          </select>
        </label>
        <span className="science-label">Cambio observado · SPHEREx QR2</span>
      </div>
      {error ? (
        <div className="notice" role="alert">
          <h2>No pudimos abrir este campo</h2>
          <p>{error}</p>
          <button
            disabled={remaining > 0}
            className="action"
            onClick={() => setReload((x) => x + 1)}
          >
            <RotateCcw size={18} />
            {remaining > 0 ? `Reintentar en ${remaining} s` : "Reintentar"}
          </button>
        </div>
      ) : !data ? (
        <div className="field-loading" role="status">
          <div className="skeleton" />
          <h2>
            {progress
              ? stages[progress.progress.stage] || "Preparando el campo"
              : "Consultando imágenes"}
          </h2>
          <p>
            Un campo nuevo puede tardar unos minutos. Puedes volver al menú.
          </p>
          {progress && (
            <>
              <progress
                max={progress.progress.total || 1}
                value={
                  progress.progress.total ? progress.progress.done : undefined
                }
                aria-label="Preparación del campo"
              />
              <p>
                {progress.progress.total > 0
                  ? `${progress.progress.done} de ${progress.progress.total}`
                  : "Buscando datos disponibles…"}
              </p>
            </>
          )}
        </div>
      ) : !current ? (
        <p className="notice">
          Este campo todavía no tiene épocas disponibles. Prueba otro detector o
          tamaño.
        </p>
      ) : (
        <>
          <div className="field-display">
            <span className="north mono">N ↑</span>
            <span className="east mono">E ←</span>
            {imageLoading && !imageError && (
              <span role="status" className="image-status">
                Cargando época…
              </span>
            )}
            {imageError ? (
              <p role="alert">
                No se pudo cargar esta imagen.{" "}
                <button
                  className="secondary"
                  onClick={() => setReload((n) => n + 1)}
                >
                  Volver a cargar
                </button>
              </p>
            ) : (
              <img
                src={imageUrl(current.image_url)}
                alt={`Imagen infrarroja del campo observado el ${current.start_utc.slice(0, 10)}, detector ${detector}`}
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
              Fecha de observación ·{" "}
              {new Date(current.start_utc).toLocaleDateString("es", {
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
                {playing ? "Pausar" : "Comparar épocas"}
              </button>
              <label>
                Intervalo
                <select
                  value={interval}
                  onChange={(e) => setIntervalMs(Number(e.target.value))}
                >
                  <option value="400">0,4 segundos</option>
                  <option value="800">0,8 segundos</option>
                  <option value="1500">1,5 segundos</option>
                </select>
              </label>
              <span className="mono">
                Época {epoch + 1} de {data.epochs.length}
              </span>
            </div>
            {data.epochs.length === 1 && (
              <p>
                Solo hay una época disponible; la comparación necesita al menos
                dos.
              </p>
            )}
            <p className="field-meta mono">
              RA {data.patch.ra.toFixed(5)}° · Dec {data.patch.dec.toFixed(5)}°
              · {data.detector.wavelength_range_um.join("–")} µm ·{" "}
              {data.size.pixel_scale_arcsec}″/px
            </p>
            <p>
              Un cambio entre imágenes no confirma un objeto nuevo. Las zonas
              transparentes no tienen datos.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
