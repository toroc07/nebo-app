// Lab route (not part of the menu): serves `shared/demo/**` read-only so the viewer can be
// tested without a backend. Files are read from disk on every request so a `git pull` shows up
// immediately.
import { readFile } from "node:fs/promises";
import path from "node:path";

// turbopackIgnore: the path leaves the project (`..`); without it Turbopack traces the whole repo
// as a build dependency and every read triggers a recompile and an endless page reload.
const root = path.resolve(
  /* turbopackIgnore: true */ process.cwd(),
  "..",
  "shared",
  "demo",
);
const types: Record<string, string> = {
  ".json": "application/json",
  ".png": "image/png",
};

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path: parts } = await params;
  const file = path.resolve(root, ...parts);
  const type = types[path.extname(file)];
  // Only inside shared/demo and only the export's file types; anything else is a 404.
  if (!type || !file.startsWith(root + path.sep)) {
    return new Response("Not found", { status: 404 });
  }
  try {
    return new Response(await readFile(file), {
      headers: { "Content-Type": type, "Cache-Control": "no-store" },
    });
  } catch {
    return new Response("Not found", { status: 404 });
  }
}
