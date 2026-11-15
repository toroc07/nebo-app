"use client";
import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import {
  ArrowUpRight,
  ArrowLeft,
  ArrowRight,
  Compass,
  Crosshair,
  BookOpen,
  SlidersHorizontal,
  Orbit,
  ChevronRight,
  RotateCcw,
} from "lucide-react";
import {
  read,
  ApiError,
  validCoordinates,
  type Target,
  type Patch,
  type Query,
} from "@/lib/api";
import Field from "./Field";
const Sky = dynamic(() => import("./Sky"), {
  ssr: false,
  loading: () => <p className="sky-loading">Cargando cielo…</p>,
});
const Flight = dynamic(() => import("./Flight"), { ssr: false });
gsap.registerPlugin(useGSAP);
type View =
  | "Inicio"
  | "Observar"
  | "Objetos destacados"
  | "Tutorial"
  | "Ajustes"
  | "Explorar"
  | "Coordenadas"
  | "Campo";
type Prefs = {
  theme: "system" | "light" | "dark";
  reduced: boolean;
  speed: number;
};
const defaults: Prefs = { theme: "system", reduced: false, speed: 800 };
const labels: Record<string, string> = {
  "barnards-star": "La estrella que nunca se queda quieta.",
  "eps-indi-b": "Dos enanas marrones, una historia compartida.",
  "wise-0855": "Un mundo frío que brilla en el infrarrojo.",
  "rw-aurigae": "Una joven estrella entre polvo y cambios.",
  "r-draconis": "El pulso de una gigante roja.",
};
export default function Nebo() {
  const [view, setView] = useState<View>("Inicio"),
    [prefs, setPrefs] = useState(defaults),
    [loaded, setLoaded] = useState(false),
    [systemReduced, setSystemReduced] = useState(false);
  const [targets, setTargets] = useState<Target[]>([]),
    [patches, setPatches] = useState<Patch[]>([]),
    [catalogError, setCatalogError] = useState(""),
    [catalogLoading, setCatalogLoading] = useState(false),
    [reload, setReload] = useState(0),
    [patchKnown, setPatchKnown] = useState(false);
  const [selected, setSelected] = useState<Target | null>(null),
    [query, setQuery] = useState<Query | null>(null),
    [ra, setRa] = useState(""),
    [dec, setDec] = useState(""),
    [formError, setFormError] = useState(""),
    [step, setStep] = useState(0),
    [flight, setFlight] = useState(0),
    [skyMounted, setSkyMounted] = useState(false);
  const root = useRef<HTMLDivElement>(null),
    heading = useRef<HTMLHeadingElement>(null),
    first = useRef(true);
  const reduced = prefs.reduced || systemReduced;
  useEffect(() => {
    try {
      const p = JSON.parse(localStorage.getItem("nebo.preferences") || "null");
      if (p)
        setPrefs({
          theme: ["system", "dark", "light"].includes(p.theme)
            ? p.theme
            : "system",
          reduced: p.reduced === true,
          speed: [400, 800, 1500].includes(p.speed) ? p.speed : 800,
        });
    } catch {}
    setLoaded(true);
    const m = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setSystemReduced(m.matches);
    update();
    m.addEventListener("change", update);
    return () => m.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem("nebo.preferences", JSON.stringify(prefs));
    } catch {
      /* Storage can be disabled; settings still apply for this session. */
    }
    document.documentElement.dataset.theme = prefs.theme;
    document.documentElement.dataset.reduced = String(reduced);
  }, [prefs, loaded, reduced]);
  const needsCatalog = ["Explorar", "Objetos destacados", "Campo"].includes(
    view,
  );
  useEffect(() => {
    if (!needsCatalog) return;
    const abort = new AbortController();
    setCatalogLoading(true);
    setCatalogError("");
    setPatchKnown(false);
    read<Target[]>("/targets", abort.signal)
      .then(setTargets)
      .catch((e) => {
        if (!abort.signal.aborted) setCatalogError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setCatalogLoading(false);
      });
    read<Patch[]>("/patches", abort.signal)
      .then((p) => {
        setPatches(p);
        setPatchKnown(true);
      })
      .catch(() => {});
    return () => abort.abort();
  }, [needsCatalog, reload]);
  useGSAP(
    () => {
      if (reduced) return;
      gsap.from(".view-content", {
        opacity: 0,
        y: 14,
        duration: 0.4,
        ease: "power3.out",
      });
      gsap.to(".landscape", {
        y: view === "Explorar" || view === "Campo" ? "18%" : "0%",
        opacity: view === "Explorar" || view === "Campo" ? 0.2 : 1,
        duration: 0.45,
      });
    },
    { scope: root, dependencies: [view, reduced], revertOnUpdate: true },
  );
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    heading.current?.focus();
  }, [view]);
  function go(v: View) {
    setView(v);
    setFormError("");
    if (v === "Explorar") {
      setSkyMounted(true);
      setFlight((x) => x + 1);
    }
  }
  function open(t: Target) {
    setSelected(t);
    setQuery({ target: t.slug });
    go("Campo");
  }
  const nav: View[] = [
    "Inicio",
    "Observar",
    "Objetos destacados",
    "Tutorial",
    "Ajustes",
  ];
  const active = ["Explorar", "Coordenadas", "Campo"].includes(view)
    ? "Observar"
    : view;
  const back = () =>
    go(
      view === "Campo"
        ? "Explorar"
        : ["Explorar", "Coordenadas"].includes(view)
          ? "Observar"
          : "Inicio",
    );
  const catalog = (
    <>
      {catalogLoading ? (
        <div className="skeleton" role="status">
          Cargando objetos del catálogo…
        </div>
      ) : catalogError ? (
        <div className="notice" role="alert">
          <h2>El catálogo no está disponible</h2>
          <p>{catalogError}</p>
          <button className="action" onClick={() => setReload((x) => x + 1)}>
            <RotateCcw size={18} />
            Reintentar
          </button>
        </div>
      ) : targets.length === 0 ? (
        <p className="notice">No hay objetos disponibles en el catálogo.</p>
      ) : (
        <div className="target-list">
          {targets.map((t, i) => (
            <button
              key={t.slug}
              className="target-row"
              onClick={() => (view === "Explorar" ? setSelected(t) : open(t))}
              aria-pressed={
                view === "Explorar" ? selected?.slug === t.slug : undefined
              }
            >
              <span className="mono target-number">0{i + 1}</span>
              <span>
                <strong>{t.name}</strong>
                <small>{labels[t.slug] || t.note}</small>
                <span className="mono readiness">
                  {!patchKnown
                    ? "Disponibilidad por consultar"
                    : patches.some(
                          (p) =>
                            p.target_slug === t.slug &&
                            p.detectors_ready.includes(t.recommended_detector),
                        )
                      ? "Imágenes preparadas"
                      : "Requiere preparación"}{" "}
                  · Detector {t.recommended_detector}
                </span>
              </span>
              <ChevronRight size={20} />
            </button>
          ))}
        </div>
      )}
    </>
  );
  return (
    <div className="app-shell" ref={root}>
      <div className="landscape" aria-hidden="true" />
      <div className="shade" aria-hidden="true" />
      <a className="skip" href="#contenido">
        Saltar al contenido
      </a>
      <header className="header">
        <a
          href="#inicio"
          className="brand"
          aria-label="Nebo, inicio"
          onClick={(e) => {
            e.preventDefault();
            go("Inicio");
          }}
        >
          <img
            className="brand-logo"
            src="/brand/nebo-logo.png"
            width={827}
            height={524}
            alt=""
          />
          <span>
            nebo<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="header-note">
          Una nueva forma de mirar arriba
          <span>Explorador del cielo · SPHEREx</span>
        </div>
        <span className="mission mono">
          <span className="status-dot" />
          DESDE LA TIERRA, MÁS LEJOS
        </span>
      </header>
      <nav className="nav" aria-label="Menú principal">
        {nav.map((n, i) => (
          <button
            key={n}
            aria-current={active === n ? "page" : undefined}
            onClick={() => go(n)}
          >
            <span className="nav-index mono">0{i + 1}</span>
            {n}
            {n === "Ajustes" && <SlidersHorizontal size={16} />}
          </button>
        ))}
      </nav>
      <main id="contenido" tabIndex={-1} className="view-content">
        {view === "Inicio" ? (
          <>
            <div className="intro">
              <p className="eyebrow">TU VENTANA AL UNIVERSO</p>
              <h1 ref={heading} tabIndex={-1}>
                El cielo tiene
                <br />
                más que contar.
              </h1>
              <p>
                Explora el cielo infrarrojo. Compara imágenes.
                <br className="desktop-break" /> Descubre lo que cambia con el
                tiempo.
              </p>
            </div>
            <div className="home-grid">
              <button
                className="tile primary-tile"
                onClick={() => go("Observar")}
              >
                <div className="tile-top">
                  <span className="mono">01 / EXPLORAR</span>
                  <Compass size={27} />
                </div>
                <div className="orbit-art" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                  <i />
                </div>
                <div className="tile-bottom">
                  <span className="tile-kicker">
                    Una mirada más allá de lo visible
                  </span>
                  <h2>
                    Observar
                    <br />
                    el cielo
                  </h2>
                  <span className="tile-link">
                    Comenzar exploración <ArrowUpRight size={24} />
                  </span>
                </div>
              </button>
              <div className="secondary-stack">
                <button
                  className="tile featured-tile"
                  onClick={() => go("Objetos destacados")}
                >
                  <div className="tile-top">
                    <span className="mono">02 / DESCUBRIR</span>
                    <ArrowUpRight size={24} />
                  </div>
                  <div className="star-art" aria-hidden="true">
                    ✦
                  </div>
                  <div className="tile-bottom">
                    <h2>
                      Hay historias
                      <br />
                      entre las estrellas.
                    </h2>
                    <span className="tile-link">
                      Objetos destacados <ArrowRight size={18} />
                    </span>
                  </div>
                </button>
                <button
                  className="tile tutorial-tile"
                  onClick={() => go("Tutorial")}
                >
                  <BookOpen size={30} />
                  <div>
                    <span className="tile-kicker">
                      No necesitas ser astrónomo
                    </span>
                    <h2>Aprende a observar</h2>
                    <span>Tu primer viaje, paso a paso</span>
                  </div>
                  <ArrowUpRight size={24} />
                </button>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="page-heading">
              <button className="back" onClick={back}>
                <ArrowLeft size={18} />
                Volver
              </button>
              <p className="eyebrow">NEBO / {active.toUpperCase()}</p>
              <h1 tabIndex={-1} ref={heading}>
                {view === "Observar"
                  ? "¿Cómo quieres mirar el cielo?"
                  : view === "Coordenadas"
                    ? "Encuentra tu campo."
                    : view === "Explorar"
                      ? "Elige tu próximo destino."
                      : view === "Campo"
                        ? selected?.name || "Tu campo de observación"
                        : view === "Objetos destacados"
                          ? "Historias del cielo."
                          : view === "Tutorial"
                            ? "Tu primera observación."
                            : "A tu manera."}
              </h1>
            </div>
            {view === "Observar" && (
              <div className="observe-grid">
                <button
                  className="tile start-tile"
                  onClick={() => go("Explorar")}
                >
                  <div className="tile-top">
                    <span className="mono">01 / SIN RUMBO FIJO</span>
                    <Compass size={32} />
                  </div>
                  <div className="tile-bottom">
                    <h2>
                      Iniciar
                      <br />
                      exploración
                    </h2>
                    <p>
                      Recorre el mapa celeste y elige un objeto para observar.
                    </p>
                    <span className="tile-link">
                      Abrir el cielo <ArrowUpRight />
                    </span>
                  </div>
                </button>
                <button
                  className="tile coordinate-tile"
                  onClick={() => go("Coordenadas")}
                >
                  <div className="tile-top">
                    <span className="mono">02 / UN DESTINO EN MENTE</span>
                    <Crosshair size={32} />
                  </div>
                  <div className="coordinate-art mono" aria-hidden="true">
                    α 269.446°
                    <br />δ +04.769°
                  </div>
                  <div className="tile-bottom">
                    <h2>
                      Buscar por
                      <br />
                      coordenadas
                    </h2>
                    <p>
                      Introduce una posición y consulta sus imágenes de SPHEREx.
                    </p>
                    <span className="tile-link">
                      Elegir coordenadas <ArrowUpRight />
                    </span>
                  </div>
                </button>
              </div>
            )}
            {view === "Coordenadas" && (
              <form
                className="surface coordinate-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!validCoordinates(ra, dec)) {
                    setFormError(
                      "Introduce RA entre 0 y menos de 360°, y Dec entre −90 y 90°.",
                    );
                    return;
                  }
                  setSelected(null);
                  setQuery({ ra: Number(ra), dec: Number(dec) });
                  go("Campo");
                }}
              >
                <Crosshair size={32} />
                <h2>Una posición. Muchas miradas.</h2>
                <p>
                  Coordenadas celestes ICRS en grados decimales. Un campo nuevo
                  puede tardar unos minutos en prepararse.
                </p>
                <label htmlFor="ra">
                  Ascensión recta (RA)<span>Desde 0 hasta menos de 360°</span>
                </label>
                <input
                  id="ra"
                  name="ra"
                  type="number"
                  step="any"
                  value={ra}
                  onChange={(e) => setRa(e.target.value)}
                  placeholder="269.446223"
                  required
                  aria-describedby={formError ? "coordinate-error" : undefined}
                />
                <label htmlFor="dec">
                  Declinación (Dec)<span>Desde −90 hasta +90°</span>
                </label>
                <input
                  id="dec"
                  name="dec"
                  type="number"
                  step="any"
                  value={dec}
                  onChange={(e) => setDec(e.target.value)}
                  placeholder="4.768780"
                  required
                  aria-describedby={formError ? "coordinate-error" : undefined}
                />
                {formError && (
                  <p role="alert" id="coordinate-error">
                    {formError}
                  </p>
                )}
                <button className="action" type="submit">
                  Ver imágenes <ArrowRight size={20} />
                </button>
              </form>
            )}
            {view === "Objetos destacados" && (
              <section className="surface catalog">
                <p>Cinco destinos para descubrir cómo cambia el universo.</p>
                {catalog}
              </section>
            )}

            {view === "Campo" && query && (
              <Field
                query={query}
                recommended={selected?.recommended_detector || 3}
                speed={prefs.speed}
                reduced={reduced}
              />
            )}
            {view === "Tutorial" && (
              <section className="surface tutorial">
                <span className="mono">PASO 0{step + 1} / 03</span>
                <div className="tutorial-symbol" aria-hidden="true">
                  {step === 0 ? (
                    <Compass size={64} />
                  ) : step === 1 ? (
                    <Crosshair size={64} />
                  ) : (
                    <Orbit size={64} />
                  )}
                </div>
                <h2>
                  {
                    [
                      "Explora sin saber coordenadas",
                      "Elige qué quieres observar",
                      "Mira lo que cambia",
                    ][step]
                  }
                </h2>
                <p>
                  {
                    [
                      "Entra en Observar y pulsa Iniciar exploración. El mapa muestra el cielo; la lista te ofrece cinco objetos para comenzar.",
                      "Selecciona un objeto y pulsa Ver imágenes. Si ya conoces una posición, puedes introducir su ascensión recta y declinación en grados.",
                      "Mueve el selector de fechas o reproduce la comparación. Usa siempre el mismo detector para comparar una banda. Las variaciones son cambios observados, no una confirmación de un planeta nuevo.",
                    ][step]
                  }
                </p>
                <div className="button-row">
                  {step > 0 && (
                    <button
                      className="secondary"
                      onClick={() => setStep((s) => s - 1)}
                    >
                      Anterior
                    </button>
                  )}
                  <button
                    className="action"
                    onClick={() =>
                      step < 2 ? setStep((s) => s + 1) : go("Observar")
                    }
                  >
                    {step < 2 ? "Siguiente" : "Comenzar"}
                    <ArrowRight size={20} />
                  </button>
                  <button
                    className="text-button"
                    onClick={() => go("Observar")}
                  >
                    Omitir tutorial
                  </button>
                </div>
              </section>
            )}
            {view === "Ajustes" && (
              <section className="surface settings">
                <h2>Prepara tu observatorio</h2>
                <p>Los cambios se guardan automáticamente en este navegador.</p>
                <label htmlFor="theme">Apariencia</label>
                <select
                  id="theme"
                  value={prefs.theme}
                  onChange={(e) =>
                    setPrefs({
                      ...prefs,
                      theme: e.target.value as Prefs["theme"],
                    })
                  }
                >
                  <option value="system">Usar tema del dispositivo</option>
                  <option value="dark">Oscuro</option>
                  <option value="light">Claro</option>
                </select>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={prefs.reduced}
                    onChange={(e) =>
                      setPrefs({ ...prefs, reduced: e.target.checked })
                    }
                  />
                  Reducir movimiento
                </label>
                <p>
                  También respetamos la preferencia de movimiento de tu
                  dispositivo.
                </p>
                <label htmlFor="speed">Intervalo de comparación</label>
                <select
                  id="speed"
                  value={prefs.speed}
                  onChange={(e) =>
                    setPrefs({ ...prefs, speed: Number(e.target.value) })
                  }
                >
                  <option value="400">Rápido · 0,4 segundos</option>
                  <option value="800">Normal · 0,8 segundos</option>
                  <option value="1500">Pausado · 1,5 segundos</option>
                </select>
                <p>La reproducción siempre comienza en pausa.</p>
              </section>
            )}
          </>
        )}
        {skyMounted && (
          <div hidden={view !== "Explorar"} className="explorer-grid">
            <div className="sky-panel">
              <Sky
                targets={targets}
                selected={selected}
                onSelect={setSelected}
              />
              <span className="map-credit">
                Mapa de referencia DSS2 · CDS Aladin
              </span>
            </div>
            <section className="surface explorer-sidebar">
              <h2>Objetos para empezar</h2>
              {catalog}
              {selected && (
                <div className="selection">
                  <h2>{selected.name}</h2>
                  <p>{labels[selected.slug] || selected.note}</p>
                  <p className="mono">
                    RA {selected.ra.toFixed(5)}°<br />
                    Dec {selected.dec.toFixed(5)}°
                  </p>
                  <button className="action" onClick={() => open(selected)}>
                    Ver imágenes <ArrowRight size={20} />
                  </button>
                </div>
              )}
            </section>
          </div>
        )}
      </main>
      <footer>
        <span>
          <span className="footer-cross">+</span> La curiosidad es el punto de
          partida.
        </span>
        <span className="mono">
          IMÁGENES SPHEREx <span className="footer-separator">/</span> NASA ·
          IPAC
        </span>
        <span className="decorative-caption">Paisaje decorativo</span>
      </footer>
      {flight > 0 && !reduced && <Flight trigger={flight} />}
    </div>
  );
}
