"use client";
import { useEffect, useRef, useState } from "react";
import type { Target } from "@/lib/api";
// Aladin's distributed package has no TypeScript declarations.
// The small interface below describes only the public methods used here.
type Viewer = {
  gotoRaDec: (ra: number, dec: number) => void;
  setFoV: (fov: number) => void;
  addCatalog: (c: unknown) => void;
  newImageSurvey: (
    url: string,
    options?: { successCallback?: (survey: { setSliceNumber: (n: number) => void }) => void },
  ) => unknown;
  setImageLayer: (layer: unknown) => void;
  // Callbacks verified in aladin.js: positionChanged gets {ra, dec, dragging}, zoomChanged the FoV.
  on: (event: "positionChanged" | "zoomChanged", handler: (payload: never) => void) => void;
  getRaDec: () => [number, number];
  showCooGrid: () => void;
  hideCooGrid: () => void;
  // aladin.js 3.9: renders the HiPS layers (plus the reticle, and the logo unless logo: false).
  getViewDataURL: (options: { format?: string; logo?: boolean }) => Promise<string>;
};
/** A still of the sky map as the cockpit shows it, with the map's on-screen size in CSS px. */
export type SkySnapshot = { url: string; width: number; height: number };
/** What the map is showing right now: its centre and horizontal field of view, in degrees. */
export type SkyView = { ra: number; dec: number; fov: number };
export type SkyLayers = { markers: boolean; grid: boolean };
/** Camera moves the cockpit screens can request (the command id is added by the page). */
export type SkyMove =
  | { action: "center" | "goto"; ra: number; dec: number }
  | { action: "fov"; fov: number };
export type SkyCommand =
  | { id: number; action: "in" | "out" | "all" }
  // Re-centres on a position the map already knows, e.g. after the user dragged away.
  | { id: number; action: "center"; ra: number; dec: number }
  // Flies to a position keeping the current zoom (all-sky locator).
  | { id: number; action: "goto"; ra: number; dec: number }
  // Sets an exact field of view (FOV gauge).
  | { id: number; action: "fov"; fov: number };
const SKY_FRAME = 40; // ~1.86 µm, inside detector 3
const SPHEREX_HIPS = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube";
export default function Sky({
  targets,
  selected,
  coordinates,
  command,
  layers,
  onSelect,
  onView,
  onCapture,
}: {
  targets: Target[];
  selected: Target | null;
  coordinates: { ra: number; dec: number } | null;
  command: SkyCommand | null;
  layers: SkyLayers;
  onSelect: (t: Target) => void;
  onView: (view: SkyView) => void;
  /**
   * Hands the page a way to take a still of the real sky map (for the analysis room's side
   * window); called with null while the map is not ready.
   */
  onCapture?: (capture: (() => Promise<SkySnapshot | null>) | null) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    fieldOfView = useRef(180),
    viewer = useRef<Viewer | null>(null),
    catalog = useRef<{
      removeAll: () => void;
      addSources: (s: unknown[]) => void;
      show: () => void;
      hide: () => void;
    } | null>(null),
    api = useRef<any>(null),
    callback = useRef(onSelect),
    viewCallback = useRef(onView),
    center = useRef({ ra: 269.446, dec: 4.769 });
  const [error, setError] = useState(false),
    [ready, setReady] = useState(false),
    [retry, setRetry] = useState(0);
  callback.current = onSelect;
  viewCallback.current = onView;
  const captureCallback = useRef(onCapture);
  captureCallback.current = onCapture;
  useEffect(() => {
    if (!ready) return;
    const take = async (): Promise<SkySnapshot | null> => {
      const node = host.current;
      if (!viewer.current || !node) return null;
      try {
        // PNG keeps the map's alpha: the room composites it on the sky panel's own navy.
        const url = await viewer.current.getViewDataURL({ format: "image/png", logo: false });
        return { url, width: node.clientWidth, height: node.clientHeight };
      } catch {
        return null; // No still: the room keeps its painted window.
      }
    };
    captureCallback.current?.(take);
    return () => captureCallback.current?.(null);
  }, [ready]);
  useEffect(() => {
    let cancelled = false;
    setError(false);
    setReady(false);
    const node = host.current;
    if (!node) return;
    import("aladin-lite")
      .then(async (m) => {
        const A = m.default;
        await A.init;
        if (cancelled) return;
        api.current = A;
        viewer.current = A.aladin(node, {
          target: "269.446 4.769",
          // Start on the SPHEREx cube and an empty HiPS list: Aladin's defaults (DSS and its
          // catalogue of surveys) would be fetched from other servers, which fails offline and
          // reports page errors, only to be replaced by the SPHEREx layer below.
          survey: SPHEREX_HIPS,
          hipsList: [],
          // No startup telemetry to the Aladin servers.
          log: false,
          fov: 180,
          projection: "AIT",
          // The cockpit is the interface: Aladin's own widgets (frame picker, coordinate box,
          // layers, projection, zoom, status bar) would break the scene. Every one of these is
          // covered by a cockpit control; the coordinate grid is a toggle in CATALOGS.
          showFullscreenControl: false,
          showShareControl: false,
          showSimbadPointerControl: false,
          showCooGridControl: false,
          showLayersControl: false,
          showSettingsControl: false,
          showProjectionControl: false,
          showZoomControl: false,
          showFrame: false,
          showFov: false,
          showCooLocation: false,
          showStatusBar: false,
        });
        // HiPS cubes load through newImageSurvey, as in the Aladin Lite 3D examples.
        viewer.current!.setImageLayer(
          viewer.current!.newImageSurvey(
            SPHEREX_HIPS,
            // Aladin starts at the middle frame (50), which is blank and has no tiles.
            { successCallback: (survey) => survey.setSliceNumber(SKY_FRAME) },
          ),
        );
        catalog.current = A.catalog({
          name: "Nebo objects",
          sourceSize: 18,
          color: "#edc181",
          onClick: (source: { data: { slug: string } }) => {
            const t = callbackTargets.current.find(
              (t) => t.slug === source.data.slug,
            );
            if (t) callback.current(t);
          },
        });
        viewer.current!.addCatalog(catalog.current);
        // Report the live view so the cockpit screens follow drags and wheel zooms too.
        const report = () =>
          viewCallback.current({ ...center.current, fov: fieldOfView.current });
        viewer.current!.on("positionChanged", (({ ra, dec }: { ra: number; dec: number }) => {
          center.current = { ra, dec };
          report();
        }) as (payload: never) => void);
        viewer.current!.on("zoomChanged", ((fov: number) => {
          // Keeps the +/− buttons stepping from the zoom the user reached with the wheel.
          fieldOfView.current = fov;
          report();
        }) as (payload: never) => void);
        report();
        setReady(true);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
      viewer.current = null;
      catalog.current = null;
      node.replaceChildren();
    };
  }, [retry]);
  const callbackTargets = useRef(targets);
  callbackTargets.current = targets;
  useEffect(() => {
    if (!ready || !api.current) return;
    catalog.current?.removeAll();
    catalog.current?.addSources(
      targets.map((t) =>
        api.current.source(t.ra, t.dec, { slug: t.slug, name: t.name }),
      ),
    );
  }, [targets, ready]);
  useEffect(() => {
    if (!ready) return;
    if (layers.markers) catalog.current?.show();
    else catalog.current?.hide();
    if (layers.grid) viewer.current?.showCooGrid();
    else viewer.current?.hideCooGrid();
  }, [layers.markers, layers.grid, ready]);
  /**
   * Moves the camera and reports the new view. Programmatic moves are reported here because
   * Aladin only guarantees positionChanged for user drags.
   */
  function fly(ra: number | null, dec: number | null, fov: number | null) {
    if (ra !== null && dec !== null) {
      viewer.current?.gotoRaDec(ra, dec);
      center.current = { ra, dec };
    }
    if (fov !== null) {
      fieldOfView.current = Math.max(0.1, Math.min(180, fov));
      viewer.current?.setFoV(fieldOfView.current);
    }
    viewCallback.current({ ...center.current, fov: fieldOfView.current });
  }
  useEffect(() => {
    if (selected && ready) fly(selected.ra, selected.dec, 8);
  }, [selected, ready]);
  useEffect(() => {
    if (coordinates && ready) fly(coordinates.ra, coordinates.dec, 8);
  }, [coordinates, ready]);
  useEffect(() => {
    if (!command || !ready) return;
    switch (command.action) {
      case "center":
        return fly(command.ra, command.dec, 8);
      case "goto":
        return fly(command.ra, command.dec, null);
      case "fov":
        return fly(null, null, command.fov);
      case "all":
        return fly(null, null, 180);
      default:
        return fly(null, null, fieldOfView.current * (command.action === "in" ? 0.5 : 2));
    }
  }, [command, ready]);
  return (
    <>
      <div
        className="aladin-host"
        ref={host}
        role="region"
        aria-label="SPHEREx sky map; use the console below to choose an object or coordinates"
      />
      {!ready && (
        <div className="sky-message" role="status">
          {error ? (
            <>
              <p>The sky map could not be loaded.</p>
              <p>You can pick an object in the console.</p>
              <button
                className="secondary"
                onClick={() => setRetry((x) => x + 1)}
              >
                Retry map
              </button>
            </>
          ) : (
            <p>Loading sky map…</p>
          )}
        </div>
      )}
      <p className="sky-help">
        Drag to move around the sky. Use the console to choose a destination.
      </p>
    </>
  );
}
