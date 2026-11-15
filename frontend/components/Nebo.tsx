"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { ArrowLeft } from "lucide-react";
import { read, type Target, type Query } from "@/lib/api";
import { parseFieldLink, type FieldLink } from "@/lib/fieldLink";
import { angularDistance, AT_MAP_CENTRE_DEG } from "@/lib/coordinates";
import Field from "./Field";
import Cockpit from "./Cockpit";
import ChatPanel from "./ChatPanel";
import { GENERAL_ROOM } from "@/lib/chat";
import HomeScene from "./HomeScene";
import type { SkyCommand, SkyLayers, SkyView } from "./Sky";
import { launchWarp, warp } from "@/lib/warp";
import NeboBoot from "./NeboBoot";
const Sky = dynamic(() => import("./Sky"), {
  ssr: false,
  loading: () => <p className="sky-loading">Loading sky…</p>,
});
const Flight = dynamic(() => import("./Flight"), { ssr: false });
gsap.registerPlugin(useGSAP);
type View = "Home" | "Explore" | "Field";
type Destination = View | "/lab/observation";
// Saved by the old settings screen; still honoured if present (the field has its own speed control).
type Prefs = { reduced: boolean; speed: number };
const defaults: Prefs = { reduced: false, speed: 800 };
export default function Nebo() {
  const router = useRouter();
  const [view, setView] = useState<View>("Home"),
    [prefs, setPrefs] = useState(defaults),
    [loaded, setLoaded] = useState(false),
    [systemReduced, setSystemReduced] = useState(false);
  const [targets, setTargets] = useState<Target[]>([]),
    [catalogError, setCatalogError] = useState(""),
    [catalogLoading, setCatalogLoading] = useState(false),
    [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<Target | null>(null),
    [skyCoordinates, setSkyCoordinates] = useState<{ ra: number; dec: number } | null>(null),
    [skyCommand, setSkyCommand] = useState<SkyCommand | null>(null),
    [skyView, setSkyView] = useState<SkyView | null>(null),
    // First-person turn between the cockpit (right = towards the analysis wall) and back.
    // "launch" = from the start screen to the cockpit (first leg of the journey).
    [turn, setTurn] = useState<"right" | "left" | "launch" | null>(null),
    // On the ground the cockpit is switched off and its glass is dark until the jump.
    [cockpitPower, setCockpitPower] = useState<"off" | "boot" | "on">("on"),
    [glassDark, setGlassDark] = useState(false),
    // START sequence: the Nebo power-on plays in the glass, then the approach tunnel. The whole
    // app is inert from START until the tunnel has finished.
    [appBoot, setAppBoot] = useState(false),
    [locked, setLocked] = useState(false),
    [screenPowered, setScreenPowered] = useState(true),
    [skyLayers, setSkyLayers] = useState<SkyLayers>({ markers: true, grid: false }),
    [query, setQuery] = useState<Query | null>(null),
    // A shared field link (?ra&dec|target&fov&det&epoch) opens the viewer directly.
    [link, setLink] = useState<FieldLink | null>(null),
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
    if (loaded && view === "Home") setSkyMounted(true);
  }, [loaded, view]);
  const turnRef = useRef(turn);
  turnRef.current = turn;
  useEffect(() => {
    try {
      const p = JSON.parse(localStorage.getItem("nebo.preferences") || "null");
      if (p)
        setPrefs({
          reduced: p.reduced === true,
          speed: [400, 800, 1500].includes(p.speed) ? p.speed : 800,
        });
    } catch {}
    const shared = parseFieldLink(location.search);
    if (shared) {
      setLink(shared);
      setQuery(shared.query);
      setView("Field");
    }
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
    document.documentElement.dataset.reduced = String(reduced);
  }, [prefs, loaded, reduced]);
  // A target link names the field once the catalogue arrives.
  useEffect(() => {
    if (link?.query.target && !selected) {
      const t = targets.find((x) => x.slug === link.query.target);
      if (t) setSelected(t);
    }
  }, [link, targets, selected]);
  const needsCatalog = ["Explore", "Field"].includes(view);
  useEffect(() => {
    if (!needsCatalog) return;
    const abort = new AbortController();
    setCatalogLoading(true);
    setCatalogError("");
    read<Target[]>("/targets", abort.signal)
      .then(setTargets)
      .catch((e) => {
        if (!abort.signal.aborted) setCatalogError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setCatalogLoading(false);
      });
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
        matchMedia("(prefers-reduced-motion: reduce)").matches ||
        turnRef.current ||
        skipEntrance.current
      ) {
        skipEntrance.current = false;
        return;
      }
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
    if (destination === "Explore") {
      setSkyMounted(true);
      setFlight((x) => x + 1);
    }
  }
  const go = contextSafe((destination: Destination) => {
    if (departing.current || destination === view || turn) return;
    const motion =
      loaded && !reduced && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Cockpit ⇄ analysis screen is one room: the camera turns instead of cutting.
    if (motion && view === "Explore" && destination === "Field") {
      setScreenPowered(false);
      setTurn("right");
      setView("Field");
      return;
    }
    if (motion && view === "Field" && destination === "Explore") {
      // Switch the screen off first, then turn back to the cockpit.
      setScreenPowered(false);
      setTimeout(() => setTurn("left"), 320);
      return;
    }
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
    entrance.current?.kill();
    gsap.set(main, { clearProps: "opacity,transform" });
    main.dataset.transition = "leaving";
    main.setAttribute("aria-busy", "true");
    main.inert = true;
    const exit = gsap.timeline({
      defaults: { ease: "power2.in" },
      onComplete: completeNavigation,
    });
    exit.to(main, { opacity: 0, y: -6, duration: 0.18 });

  });
  // Timers of the launch sequence (power-up, jump), cleared if the page leaves mid-way.
  const launchTimers = useRef<number[]>([]);
  useEffect(() => () => launchTimers.current.forEach(clearTimeout), []);

  // Every button stays locked from START until the approach tunnel has played out. The tunnel
  // reports its end through the warp controller; a safety timer unlocks anyway if it never does.
  const approaching = useRef(false);
  const unlockTimer = useRef<number | undefined>(undefined);
  function lock() {
    setLocked(true);
    window.clearTimeout(unlockTimer.current);
    unlockTimer.current = window.setTimeout(() => {
      approaching.current = false;
      setLocked(false);
    }, 25_000);
  }
  useEffect(() => {
    const off = warp.subscribe(() => {
      if (approaching.current && !warp.isActive()) {
        approaching.current = false;
        window.clearTimeout(unlockTimer.current);
        setLocked(false);
      }
    });
    return () => {
      off();
      window.clearTimeout(unlockTimer.current);
    };
  }, []);
  // Set before a view change that the camera already animated, so the generic fade-in is skipped.
  const skipEntrance = useRef(false);

  /** After the pan to the cockpit: screens power up, then the jump runs inside the glass. */
  function powerUpAndJump() {
    const later = (ms: number, fn: () => void) => launchTimers.current.push(window.setTimeout(fn, ms));
    setCockpitPower("boot");
    // The tunnel starts once the screens are on (power-on is 520 ms + staggered delays).
    later(900, () => {
      setCockpitPower("on");
      approaching.current = true;
      launchWarp("explore", "cockpit");
    });
    // The tunnel's own fade-in is 0.35 s; lift the dark glass only once it is covered.
    later(900 + 450, () => setGlassDark(false));
  }

  // Layout effect: the strip must be in place before the first frame is painted, or the newly
  // shown wall would flash at its final position for one frame.
  useLayoutEffect(() => {
    if (!turn) return;
    const explorer = root.current?.querySelector<HTMLElement>(".explorer-grid");
    const field = root.current?.querySelector<HTMLElement>('[data-console="field"]');
    const home = root.current?.querySelector<HTMLElement>('[data-scene="home"]');
    const corner = root.current?.querySelector<HTMLElement>(".turn-corner");
    // Each turn pans across [left wall · painted corner · right wall]; the camera faces the left
    // wall at the start of a turn to the right, and the right wall at the start of a turn left.
    const [leftWall, rightWall] = turn === "launch" ? [home, explorer] : [explorer, field];
    const finish = () => {
      // Only the walls that stay get their position reset. The one being left (the start
      // screen, or the analysis screen on the way back) keeps its off-screen offset until React
      // unmounts it; resetting it here put it back at x = 0, over everything, for one frame.
      const leaving = turn === "launch" ? home : turn === "left" ? field : null;
      [leftWall, rightWall].forEach((wall) => {
        if (wall && wall !== leaving) gsap.set(wall, { clearProps: "transform" });
      });
      skipEntrance.current = true;
      if (turn === "launch") {
        setView("Explore");
        setTurn(null);
        // The Nebo power-on plays first; its end starts the approach (powerUpAndJump).
        setAppBoot(true);
      } else if (turn === "right") {
        setTurn(null);
        setScreenPowered(true);
      } else {
        setView("Explore");
        setTurn(null);
        setScreenPowered(true);
      }
    };
    if (!leftWall || !rightWall || !corner) return finish();
    /*
     * The turn is a camera pan across one continuous strip. The middle panel was painted to join
     * the two views (turn-corner.webp, home-corner.webp), so the pan never shows a seam or the
     * space behind the walls. Flat translations only: no 3D, which clipped the walls.
     */
    const vw = window.innerWidth;
    // Both corner images are 1536 × 1024: the left 600 px repeat the left wall's right edge,
    // the right 600 px the right wall's left edge (at their on-screen scale for 16:9), and the
    // 336 px between were painted to join them. They overlay the live views where they match.
    const scale = corner.offsetHeight / 1024;
    const overlap = 600 * scale;
    const gap = 336 * scale;
    const towardRight = turn !== "left";
    // Strip offsets from the left wall's x: corner at vw − overlap, right wall at vw + gap.
    const start = towardRight ? 0 : -(vw + gap);
    const end = towardRight ? -(vw + gap) : 0;
    const timeline = gsap.timeline({ onComplete: finish, defaults: { duration: 1.25, ease: "power2.inOut" } });
    timeline
      .fromTo(leftWall, { x: start }, { x: end }, 0)
      .fromTo(corner, { x: start + vw - overlap }, { x: end + vw - overlap }, 0)
      .fromTo(rightWall, { x: start + vw + gap }, { x: end + vw + gap }, 0);
    return () => {
      timeline.kill();
    };
  }, [turn]);

  /** START on the ground: dark cockpit, pan to it, power up, jump. */
  function startJourney() {
    if (turn || departing.current) return;
    const motion = loaded && !reduced && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!motion || !root.current?.querySelector(".explorer-grid")) {
      go("Explore");
      return;
    }
    lock();
    setCockpitPower("off");
    setGlassDark(true);
    setTurn("launch");
  }
  // Back from a field returns to the last screen that was not a field (the sky explorer).
  const fieldOrigin = useRef<View>("Explore");
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
        : "Home",
    );
  return (
    <div
      className="app-shell"
      ref={root}
      inert={locked}
      aria-busy={locked || undefined}
    >
      <a className="skip" href="#content">
        Skip to content
      </a>
      {/* Public chat, only in the sky explorer (it goes away on View images): the selected
          object's room, else the general one. */}
      {view === "Explore" && (
        <ChatPanel
          room={selected?.slug ?? GENERAL_ROOM}
          roomLabel={selected ? `${selected.name} chat` : "General chat"}
        />
      )}
      <main id="content" tabIndex={-1} className="view-content">
        {view === "Home" ? (
          <HomeScene headingRef={heading} onStart={startJourney} />
        ) : (
          <>
            {/* The field console draws its own Back button and title inside the ship screen. */}
            {view !== "Field" && (
              <div className="page-heading">
                <button className="back" onClick={back}>
                  <ArrowLeft size={18} />
                  Back
                </button>
                <h1 className="sr-only" tabIndex={-1} ref={heading}>
                  Choose your next destination.
                </h1>
              </div>
            )}
            {view === "Field" && query &&
              // A target link without det waits for the catalogue's recommended detector.
              !(query.target && !selected && !link?.detector && !targets.length && !catalogError) && (
              <Field
                query={query}
                target={selected}
                catalog={targets}
                title={selected?.name || (link?.query === query && link.name) || "Your observation field"}
                name={link?.query === query ? link.name : undefined}
                headingRef={heading}
                onBack={back}
                powered={screenPowered}
                recommended={(link?.query === query && link.detector) || selected?.recommended_detector || 3}
                initialSize={link?.query === query ? link.size : undefined}
                initialEpoch={link?.query === query ? link.epoch : undefined}
                speed={prefs.speed}
                reduced={reduced}
              />
            )}
          </>
        )}
        {turn && <div className="turn-corner" data-kind={turn === "launch" ? "launch" : "turn"} aria-hidden="true" />}
        {skyMounted && (
          <div
            hidden={!["Explore", "Field", "Home"].includes(view) && !turn}
            className="explorer-grid"
            data-glass={glassDark ? "dark" : undefined}
            inert={view !== "Explore" && !turn}
            aria-hidden={view !== "Explore" && !turn ? true : undefined}
          >
            {/*
              * While the analysis screen is up, the cockpit stays mounted and painted behind it
              * (inert, aria-hidden). display:none would make Aladin resize and reload on the way
              * back (a stalled turn); visibility:hidden would blank its WebGL sky (broken glass).
              */}
            <div className="sky-panel">
              {appBoot && (
                <NeboBoot
                  onDone={() => {
                    setAppBoot(false);
                    powerUpAndJump();
                  }}
                />
              )}
              <Sky
                targets={targets}
                selected={selected}
                coordinates={skyCoordinates}
                command={skyCommand}
                layers={skyLayers}
                onView={setSkyView}
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
              onView={(p) => {
                // The console calls an object within 3′ "at the map centre": open that object, not a new
                // patch beside it (the backend only reuses a patch within 30″). Typed coordinates are
                // left to the backend's match (P0-6).
                const centred = !skyCoordinates && targets.find(
                  (t) => angularDistance(p.ra, p.dec, t.ra, t.dec) < AT_MAP_CENTRE_DEG,
                );
                if (selected) open(selected);
                else if (centred) open(centred);
                else {
                  setQuery({ ra: p.ra, dec: p.dec });
                  go("Field");
                }
              }}
              onRetry={() => setReload((x) => x + 1)}
              skyView={skyView}
              layers={skyLayers}
              onLayers={setSkyLayers}
              onCommand={(c) => setSkyCommand({ id: Date.now(), ...c })}
              power={cockpitPower}
            />
          </div>
        )}
      </main>
      {flight > 0 && !reduced && <Flight trigger={flight} />}
    </div>
  );
}
