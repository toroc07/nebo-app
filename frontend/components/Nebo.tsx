"use client";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
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
import Cockpit from "./Cockpit";
import type { SkyCommand } from "./Sky";
import { launchWarp } from "@/lib/warp";
const Sky = dynamic(() => import("./Sky"), {
  ssr: false,
  loading: () => <p className="sky-loading">Loading sky…</p>,
});
const Flight = dynamic(() => import("./Flight"), { ssr: false });
gsap.registerPlugin(useGSAP);
type View =
  | "Home"
  | "Observe"
  | "Featured objects"
  | "Tutorial"
  | "Settings"
  | "Explore"
  | "Coordinates"
  | "Field";
type Destination = View | "/lab/observation";
type Prefs = {
  theme: "system" | "light" | "dark";
  reduced: boolean;
  speed: number;
};
const defaults: Prefs = { theme: "system", reduced: false, speed: 800 };
const labels: Record<string, string> = {
  "barnards-star": "The star that never stands still.",
  "eps-indi-b": "Two brown dwarfs, one shared story.",
  "wise-0855": "A cold world glowing in the infrared.",
  "rw-aurigae": "A young star among dust and change.",
  "r-draconis": "The pulse of a red giant.",
};
function PanelImage({ src }: { src: string }) {
  return (
    <span className="panel-visual" aria-hidden="true">
      <img className="panel-image" src={src} alt="" width={1200} height={800} />
      <img
        className="panel-image panel-image-sharp"
        src={src}
        alt=""
        width={1200}
        height={800}
      />
    </span>
  );
}
export default function Nebo() {
  const router = useRouter();
  const [view, setView] = useState<View>("Home"),
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
    [skyCoordinates, setSkyCoordinates] = useState<{ ra: number; dec: number } | null>(null),
    [skyCommand, setSkyCommand] = useState<SkyCommand | null>(null),
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
  const entrance = useRef<gsap.core.Timeline | null>(null),
    departing = useRef(false),
    pending = useRef<Destination | null>(null);
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
  const needsCatalog = ["Explore", "Featured objects", "Field"].includes(view);
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
  const { contextSafe } = useGSAP(
    () => {
      const main = root.current?.querySelector<HTMLElement>(".view-content");
      if (main) {
        main.inert = false;
        main.removeAttribute("aria-busy");
        delete main.dataset.transition;
      }
      departing.current = false;
      // A preference change can cancel an exit; still honor the chosen destination.
      if (pending.current) {
        completeNavigation();
        return;
      }
      if (
        !loaded ||
        reduced ||
        matchMedia("(prefers-reduced-motion: reduce)").matches
      )
        return;
      const menu = root.current?.querySelector(".panel-menu");
      if (main) main.dataset.transition = "entering";
      const timeline = gsap.timeline({
        defaults: { ease: "power3.out" },
        onComplete: () => {
          if (main?.dataset.transition === "entering")
            delete main.dataset.transition;
        },
      });
      entrance.current = timeline;
      timeline.fromTo(
        ".view-content",
        { opacity: 0 },
        {
          opacity: 1,
          duration: 0.18,
          clearProps: "opacity",
        },
      );
      if (menu) {
        const cards = menu.querySelectorAll(".image-tile");
        // CSS hover resumes after the coordinated opening finishes.
        timeline.fromTo(
          cards,
          { opacity: 0, scale: 0.965, y: 12 },
          {
            opacity: 1,
            scale: 1,
            y: 0,
            duration: 0.3,
            stagger: Math.min(0.04, 0.16 / cards.length),
            clearProps: "opacity,transform",
          },
          0.04,
        );
        timeline.fromTo(
          menu.querySelectorAll(
            ".tile-bottom, .tutorial-tile > div, .settings-tile > div",
          ),
          {
            opacity: 0,
            y: 10,
          },
          {
            opacity: 1,
            y: 0,
            duration: 0.36,
            stagger: 0.03,
            clearProps: "opacity,transform",
          },
          0.08,
        );
      }
      gsap.to(".landscape", {
        y: view === "Explore" || view === "Field" ? "18%" : "0%",
        opacity: view === "Explore" || view === "Field" ? 0.2 : 1,
        duration: 0.45,
      });
    },
    {
      scope: root,
      dependencies: [view, reduced, loaded],
      revertOnUpdate: true,
    },
  );
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    heading.current?.focus();
  }, [view]);
  function completeNavigation() {
    const destination = pending.current;
    pending.current = null;
    if (!destination) return;
    if (destination === "/lab/observation") {
      router.push(destination);
      return;
    }
    departing.current = false;
    setView(destination);
    setFormError("");
    if (destination === "Explore") {
      setSkyMounted(true);
      setFlight((x) => x + 1);
    }
  }
  const go = contextSafe((destination: Destination) => {
    if (departing.current || destination === view) return;
    // The tunnel starts right away and runs as the loading screen of the destination (the sky
    // globe, or the observation viewer across the route change): components/WarpOverlay.tsx.
    if (destination === "Explore") launchWarp("explore");
    else if (destination === "/lab/observation") launchWarp("viewer");
    pending.current = destination;
    const main = root.current?.querySelector<HTMLElement>(".view-content");
    if (
      !main ||
      !loaded ||
      reduced ||
      matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      completeNavigation();
      return;
    }
    departing.current = true;
    const selected =
      document.activeElement?.closest<HTMLElement>(".image-tile");
    const menu = main.querySelector<HTMLElement>(".panel-menu");
    const cards = Array.from(
      menu?.querySelectorAll<HTMLElement>(".image-tile") ?? [],
    );
    const center = menu?.getBoundingClientRect();
    const directions = new Map(
      cards.map((card) => {
        const rect = card.getBoundingClientRect();
        return [
          card,
          center && rect.left + rect.width / 2 < center.left + center.width / 2
            ? -1
            : 1,
        ];
      }),
    );
    entrance.current?.kill();
    gsap.set(main, { clearProps: "opacity,transform" });
    main.dataset.transition = "leaving";
    main.setAttribute("aria-busy", "true");
    main.inert = true;
    const exit = gsap.timeline({
      defaults: { ease: "power2.in" },
      onComplete: completeNavigation,
    });
    if (cards.length) {
      const others = cards.filter((card) => card !== selected);
      exit.to(
        others,
        {
          opacity: 0,
          scale: 0.94,
          x: (_index, card) => (directions.get(card) ?? 1) * 18,
          duration: 0.22,
          stagger: 0.02,
        },
        0,
      );
      if (selected && cards.includes(selected)) {
        exit.to(
          selected,
          {
            scale: 1.045,
            opacity: destination === "/lab/observation" ? 0.15 : 0,
            duration: 0.26,
          },
          0.04,
        );
      }
    } else {
      exit.to(main, { opacity: 0, y: -6, duration: 0.18 });
    }
  });
  // A field can be opened from Featured objects, the sky explorer or the coordinates form. Back
  // returns to whichever one it was opened from: the last screen that was not a field.
  const fieldOrigin = useRef<View>("Observe");
  useEffect(() => {
    if (view !== "Field") fieldOrigin.current = view;
  }, [view]);
  function open(t: Target) {
    setSelected(t);
    setQuery({ target: t.slug });
    go("Field");
  }
  const back = () =>
    go(
      view === "Field"
        ? fieldOrigin.current
        : ["Explore", "Coordinates"].includes(view)
          ? "Observe"
          : "Home",
    );
  function illuminatePanels(event: PointerEvent<HTMLElement>) {
    if (event.pointerType !== "mouse") return;
    const lights = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(".image-tile"),
      (tile) => {
        const rect = tile.getBoundingClientRect();
        const dx = Math.max(
          rect.left - event.clientX,
          0,
          event.clientX - rect.right,
        );
        const dy = Math.max(
          rect.top - event.clientY,
          0,
          event.clientY - rect.bottom,
        );
        return { tile, near: String(Math.hypot(dx, dy) < 64) };
      },
    );
    lights.forEach(({ tile, near }) => {
      tile.dataset.near = near;
    });
  }

  function clearPanelLight(event: PointerEvent<HTMLElement>) {
    event.currentTarget
      .querySelectorAll<HTMLElement>(".image-tile")
      .forEach((tile) => {
        delete tile.dataset.near;
      });
  }
  const catalog = (
    <>
      {catalogLoading ? (
        <div className="skeleton" role="status">
          Loading catalog objects…
        </div>
      ) : catalogError ? (
        <div className="notice" role="alert">
          <h2>The catalog is unavailable</h2>
          <p>{catalogError}</p>
          <button className="action" onClick={() => setReload((x) => x + 1)}>
            <RotateCcw size={18} />
            Retry
          </button>
        </div>
      ) : targets.length === 0 ? (
        <p className="notice">No objects are available in the catalog.</p>
      ) : (
        <div className="target-list">
          {targets.map((t, i) => (
            <button
              key={t.slug}
              className="target-row"
              onClick={() => (view === "Explore" ? setSelected(t) : open(t))}
              aria-pressed={
                view === "Explore" ? selected?.slug === t.slug : undefined
              }
            >
              <span className="mono target-number">0{i + 1}</span>
              <span>
                <strong>{t.name}</strong>
                <small>{labels[t.slug] || t.note}</small>
                <span className="mono readiness">
                  {!patchKnown
                    ? "Availability to be checked"
                    : patches.some(
                          (p) =>
                            p.target_slug === t.slug &&
                            p.detectors_ready.includes(t.recommended_detector),
                        )
                      ? "Images ready"
                      : "Needs preparation"}{" "}
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
      <a className="skip" href="#content">
        Skip to content
      </a>
      <header className="header">
        <a
          href="#home"
          className="brand"
          aria-label="Nebo, home"
          onClick={(e) => {
            e.preventDefault();
            go("Home");
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
      </header>
      <main id="content" tabIndex={-1} className="view-content">
        {view === "Home" ? (
          <>
            <h1 className="sr-only" ref={heading} tabIndex={-1}>
              Home
            </h1>
            <nav
              className="home-grid panel-menu"
              aria-label="Home panel"
              onPointerMove={illuminatePanels}
              onPointerLeave={clearPanelLight}
            >
              <button
                className="tile primary-tile image-tile"
                onClick={() => go("Observe")}
              >
                <PanelImage src="/panels/deep-field.png" />
                <div className="tile-top">
                  <span className="mono">01 / EXPLORE</span>
                  <Compass size={27} />
                </div>
                <div className="tile-bottom">
                  <h2>
                    Observe
                    <br />
                    the sky
                  </h2>
                  <span className="tile-link">
                    Start exploring <ArrowUpRight size={24} />
                  </span>
                </div>
              </button>
              <div className="secondary-stack">
                <button
                  className="tile featured-tile image-tile"
                  onClick={() => go("Featured objects")}
                >
                  <PanelImage src="/panels/nebula.png" />
                  <div className="tile-top">
                    <span className="mono">02 / DISCOVER</span>
                    <ArrowUpRight size={24} />
                  </div>
                  <div className="tile-bottom">
                    <h2>Featured objects</h2>
                    <span className="tile-link">
                      View objects <ArrowRight size={18} />
                    </span>
                  </div>
                </button>
                <button
                  className="tile tutorial-tile image-tile"
                  onClick={() => go("Tutorial")}
                >
                  <PanelImage src="/panels/telescope.jpg" />
                  <BookOpen size={30} />
                  <div>
                    <h2>Tutorial</h2>
                    <span>Your first trip, step by step</span>
                  </div>
                  <ArrowUpRight size={24} />
                </button>
              </div>
              <button
                className="tile settings-tile image-tile"
                onClick={() => go("Settings")}
              >
                <PanelImage src="/panels/controls.svg" />
                <SlidersHorizontal size={24} aria-hidden="true" />
                <div>
                  <h2>Settings</h2>
                  <span>Appearance and motion</span>
                </div>
                <ArrowUpRight size={24} aria-hidden="true" />
              </button>
            </nav>
          </>
        ) : (
          <>
            <div
              className={`page-heading${view === "Observe" ? " observe-heading" : ""}`}
            >
              <button className="back" onClick={back}>
                <ArrowLeft size={18} />
                Back
              </button>
              <h1
                className={["Observe", "Explore"].includes(view) ? "sr-only" : undefined}
                tabIndex={-1}
                ref={heading}
              >
                {view === "Observe"
                  ? "Observe"
                  : view === "Coordinates"
                    ? "Find your field."
                    : view === "Explore"
                      ? "Choose your next destination."
                      : view === "Field"
                        ? selected?.name || "Your observation field"
                        : view === "Featured objects"
                          ? "Featured objects"
                          : view === "Tutorial"
                            ? "Tutorial"
                            : "Settings"}
              </h1>
            </div>
            {view === "Observe" && (
              <nav
                className="observe-grid panel-menu"
                aria-label="Observe panel"
                onPointerMove={illuminatePanels}
                onPointerLeave={clearPanelLight}
              >
                <button
                  className="tile start-tile image-tile"
                  onClick={() => go("Explore")}
                >
                  <PanelImage src="/panels/cartwheel.png" />
                  <div className="tile-top">
                    <Compass size={32} />
                  </div>
                  <div className="tile-bottom">
                    <h2>
                      Begin
                      <br />
                      exploring
                    </h2>
                    <p>Explore images at your own pace.</p>
                    <span className="tile-link">
                      Open the images <ArrowUpRight />
                    </span>
                  </div>
                </button>
                <button
                  className="tile coordinate-tile image-tile"
                  onClick={() => go("Coordinates")}
                >
                  <PanelImage src="/panels/coordinates.svg" />
                  <div className="tile-top">
                    <Crosshair size={32} />
                  </div>
                  <div className="tile-bottom">
                    <h2>
                      Search by
                      <br />
                      coordinates
                    </h2>
                    <p>Enter a position and view its SPHEREx images.</p>
                    <span className="tile-link">
                      Choose coordinates <ArrowUpRight />
                    </span>
                  </div>
                </button>
              </nav>
            )}
            {view === "Coordinates" && (
              <form
                className="surface coordinate-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!validCoordinates(ra, dec)) {
                    setFormError(
                      "Enter RA from 0 up to, but not including, 360°, and Dec between −90 and 90°.",
                    );
                    return;
                  }
                  setSelected(null);
                  setQuery({ ra: Number(ra), dec: Number(dec) });
                  go("Field");
                }}
              >
                <Crosshair size={32} />
                <h2>One position. Many views.</h2>
                <p>
                  ICRS celestial coordinates in decimal degrees. A new field can
                  take a few minutes to prepare.
                </p>
                <label htmlFor="ra">
                  Right ascension (RA)
                  <span>From 0 up to, but not including, 360°</span>
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
                  Declination (Dec)<span>From −90 to +90°</span>
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
                  View images <ArrowRight size={20} />
                </button>
              </form>
            )}
            {view === "Featured objects" && (
              <section className="surface catalog">
                <p>Five destinations to discover how the universe changes.</p>
                {catalog}
              </section>
            )}

            {view === "Field" && query && (
              <Field
                query={query}
                recommended={selected?.recommended_detector || 3}
                speed={prefs.speed}
                reduced={reduced}
              />
            )}
            {view === "Tutorial" && (
              <section className="surface tutorial">
                <span className="mono">STEP 0{step + 1} / 03</span>
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
                      "Explore without knowing coordinates",
                      "Choose what you want to observe",
                      "See what changes",
                    ][step]
                  }
                </h2>
                <p>
                  {
                    [
                      "Go to Observe and press Begin exploring. The image fills your screen: scroll or pinch to zoom, drag to pan, and click to read a coordinate.",
                      "Select an object and press View images. If you already know a position, you can enter its right ascension and declination in degrees.",
                      "Move the date selector or play the comparison. Always use the same detector to compare one band. Variations are observed changes, not confirmation of a new planet.",
                    ][step]
                  }
                </p>
                <div className="button-row">
                  {step > 0 && (
                    <button
                      className="secondary"
                      onClick={() => setStep((s) => s - 1)}
                    >
                      Previous
                    </button>
                  )}
                  <button
                    className="action"
                    onClick={() =>
                      step < 2 ? setStep((s) => s + 1) : go("Observe")
                    }
                  >
                    {step < 2 ? "Next" : "Start"}
                    <ArrowRight size={20} />
                  </button>
                  <button className="text-button" onClick={() => go("Observe")}>
                    Skip tutorial
                  </button>
                </div>
              </section>
            )}
            {view === "Settings" && (
              <section className="surface settings">
                <h2>Set up your observatory</h2>
                <p>Changes are saved automatically in this browser.</p>
                <label htmlFor="theme">Appearance</label>
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
                  <option value="system">Use device theme</option>
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                </select>
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={prefs.reduced}
                    onChange={(e) =>
                      setPrefs({ ...prefs, reduced: e.target.checked })
                    }
                  />
                  Reduce motion
                </label>
                <p>We also respect your device&apos;s motion preference.</p>
                <label htmlFor="speed">Comparison interval</label>
                <select
                  id="speed"
                  value={prefs.speed}
                  onChange={(e) =>
                    setPrefs({ ...prefs, speed: Number(e.target.value) })
                  }
                >
                  <option value="400">Fast · 0.4 seconds</option>
                  <option value="800">Normal · 0.8 seconds</option>
                  <option value="1500">Slow · 1.5 seconds</option>
                </select>
                <p>Playback always starts paused.</p>
              </section>
            )}
          </>
        )}
        {skyMounted && (
          <div hidden={view !== "Explore"} className="explorer-grid">
            <div className="sky-panel">
              <Sky
                targets={targets}
                selected={selected}
                coordinates={skyCoordinates}
                command={skyCommand}
                onSelect={(target) => { setSkyCoordinates(null); setSelected(target); }}
              />
              <span className="map-credit">
                SPHEREx all-sky map · NASA/IPAC IRSA
              </span>
            </div>
            <Cockpit
              targets={targets}
              selected={selected}
              coordinates={skyCoordinates}
              catalogLoading={catalogLoading}
              catalogError={catalogError}
              onSelect={(target) => {
                setSkyCoordinates(null);
                setSelected(target);
              }}
              onCoordinates={(p) => {
                setSelected(null);
                setSkyCoordinates(p);
              }}
              onZoom={(action) => setSkyCommand({ id: Date.now(), action })}
              onCenter={(p) => setSkyCommand({ id: Date.now(), action: "center", ...p })}
              onView={() => {
                if (selected) open(selected);
                else if (skyCoordinates) {
                  setQuery(skyCoordinates);
                  go("Field");
                }
              }}
              onRetry={() => setReload((x) => x + 1)}
            />
          </div>
        )}
      </main>
      <footer>
        <span className="mono">
          SPHEREx IMAGES <span className="footer-separator">/</span> NASA · IPAC
        </span>
      </footer>
      {flight > 0 && !reduced && <Flight trigger={flight} />}
    </div>
  );
}
