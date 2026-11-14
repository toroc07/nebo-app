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
};
const SKY_FRAME = 40; // ~1.86 µm, inside detector 3
export default function Sky({
  targets,
  selected,
  onSelect,
}: {
  targets: Target[];
  selected: Target | null;
  onSelect: (t: Target) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    viewer = useRef<Viewer | null>(null),
    catalog = useRef<{
      removeAll: () => void;
      addSources: (s: unknown[]) => void;
    } | null>(null),
    api = useRef<any>(null),
    callback = useRef(onSelect);
  const [error, setError] = useState(false),
    [ready, setReady] = useState(false),
    [retry, setRetry] = useState(0);
  callback.current = onSelect;
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
          fov: 180,
          projection: "AIT",
          showFullscreenControl: false,
          showShareControl: false,
          showSimbadPointerControl: false,
          showCooGridControl: true,
        });
        // HiPS cubes load through newImageSurvey, as in the Aladin Lite 3D examples.
        viewer.current!.setImageLayer(
          viewer.current!.newImageSurvey(
            "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube",
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
    if (selected && ready) {
      viewer.current?.gotoRaDec(selected.ra, selected.dec);
      viewer.current?.setFoV(8);
    }
  }, [selected, ready]);
  return (
    <>
      <div
        className="aladin-host"
        ref={host}
        role="region"
        aria-label="Sky map; the object list is an alternative way to select"
      />
      {!ready && (
        <div className="sky-message" role="status">
          {error ? (
            <>
              <p>The sky map could not be loaded.</p>
              <p>You can pick an object from the list.</p>
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
        Drag to move around the sky. You can also pick an object from the list.
      </p>
    </>
  );
}
