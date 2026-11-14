// Laboratorio (no es parte del menú): sirve en solo lectura `shared/demo/**` para probar el
// visor sin backend. Se lee del disco en cada petición para que un `git pull` se refleje solo.
import { readFile } from "node:fs/promises";
import path from "node:path";

// turbopackIgnore: la ruta sale del proyecto (`..`); sin esto Turbopack rastrea todo el repo como
// dependencia del build y cada lectura provoca una recompilación y una recarga en bucle.
const root = path.resolve(/* turbopackIgnore: true */ process.cwd(), "..", "shared", "demo");
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
  // Solo dentro de shared/demo y solo los tipos del export; cualquier otra cosa es 404.
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
