// Loading all field-of-view levels of one observation (see lib/lab/fov.ts).
import {
  epochImageUrl,
  loadTimeline,
  type LabTimeline,
  type Palette,
  type Source,
} from "./contract";
import { sizeNames, type Level, type SizeName } from "./fov";

export type LabLevels = Partial<Record<SizeName, LabTimeline>>;

/** Levels that were loaded, smallest first. */
export function loadedLevels(levels: LabLevels): LabTimeline[] {
  return sizeNames.flatMap((name) => (levels[name] ? [levels[name]] : []));
}

/** The geometry the viewer needs, smallest first. */
export function levelGeometry(levels: LabLevels): Level[] {
  return sizeNames.flatMap((name) => {
    const t = levels[name];
    return t
      ? [{ name, width: t.size.width_px, height: t.size.height_px }]
      : [];
  });
}

/** Every epoch image of every level, so changing level or epoch never waits for the network. */
export function allImageUrls(source: Source, levels: LabLevels): string[] {
  return loadedLevels(levels).flatMap((t) =>
    t.epochs.map((e) => epochImageUrl(source, e, t.palette)),
  );
}

/** Resolves when the image is in the browser cache; rejects if it cannot be loaded. */
export function loadImage(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => reject(new Error(`Could not load ${url}`));
    img.src = url;
  });
}

/**
 * Loads the medium level first (it is the one shown at start, and for the real API the one that
 * may need to be built, with progress), then the other two. Those are central crops of the same
 * patch, so after the first request they are cheap. A level that fails to load is skipped: the
 * viewer just has a shorter ladder. Only a failing medium level is an error.
 */
export async function loadLevels(
  source: Source,
  slug: string,
  detector: number,
  palette: Palette,
  signal: AbortSignal,
  onBuilding?: (stage: string, done: number, total: number) => void,
): Promise<LabLevels> {
  const medium = await loadTimeline(
    source,
    slug,
    detector,
    "medium",
    signal,
    onBuilding,
    palette,
  );
  const others: SizeName[] = ["small", "large"];
  const settled = await Promise.allSettled(
    others.map((name) =>
      loadTimeline(source, slug, detector, name, signal, undefined, palette),
    ),
  );
  const levels: LabLevels = { medium };
  settled.forEach((result, i) => {
    if (result.status === "fulfilled") levels[others[i]] = result.value;
  });
  return levels;
}
