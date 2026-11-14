// Lab route (not part of the menu): serves the synthetic demo exports in `shared/` read-only so
// the viewer can be tested without a backend. Files are read from disk on every request so a
// `git pull` shows up quickly.
//
// URL layout, one folder per display palette (see shared/README.md):
//   /lab/demo/<file>           -> shared/demo/<file>          grey (the raw infrared band)
//   /lab/demo/amber/<file>     -> shared/demo-color/<file>    amber palette
//   /lab/demo/inferno/<file>   -> shared/demo-inferno/<file>  inferno palette
import { readFile } from "node:fs/promises";
import path from "node:path";

// turbopackIgnore: the path leaves the project (`..`); without it Turbopack traces the whole repo
// as a build dependency and every read triggers a recompile and an endless page reload.
const shared = path.resolve(
  /* turbopackIgnore: true */ process.cwd(),
  "..",
  "shared",
);
const folders: Record<string, string> = {
  amber: "demo-color",
  inferno: "demo-inferno",
};
const types: Record<string, string> = {
  ".json": "application/json",
  ".png": "image/png",
};

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: parts } = await params;
  const folder = folders[parts[0]];
  const root = path.join(shared, folder ?? "demo");
  const file = path.resolve(root, ...(folder ? parts.slice(1) : parts));
  const type = types[path.extname(file)];
  // Only inside the chosen demo folder and only the export's file types; anything else is a 404.
  if (!type || !file.startsWith(root + path.sep)) {
    return new Response("Not found", { status: 404 });
  }
  try {
    return new Response(await readFile(file), {
      // A short cache lets the viewer preload the other palette's images and swap to them
      // without a second download; a minute is still quick enough to see regenerated exports.
      headers: { "Content-Type": type, "Cache-Control": "private, max-age=60" },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
