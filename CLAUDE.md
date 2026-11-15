# Nebo — SPHEREx sky viewer

Web viewer of the infrared sky with planetarium-style zoom: from the whole sky down to a field,
and there, comparing SPHEREx epochs (time slider + blink comparator). Project for the
"Planet X and SPHEREx" challenge of NASA Space Apps 2026. Full plan: the team's Claude Docs
document (https://claude.ai/artifact/9AHiC9z8fX7MRQ5rxg1iDE).

## Status

| Folder | Status |
| --- | --- |
| `backend/` | Done: FastAPI + PostgreSQL API. Details and contract in `backend/README.md` |
| `frontend/` | In progress: Next.js menu, sky explorer and field viewer. See `frontend/README.md`; `docs/observation-lab.md` keeps the findings of the removed `/lab/observation` viewer |
| `shared/` | Synthetic static demo export (`shared/demo`), same shape as the API |
| `data/`, `docs/` | `docs/` holds the frontend plan and the observation lab findings; `data/` is a placeholder |

## Frontend stack (decided, do not re-litigate)

Next.js + TypeScript · Aladin Lite v3 (sky, HiPS, footprints, zoom) · react-three-fiber +
GLSL shader + postprocessing (tunnel/warp) · GSAP (one timeline syncs camera, shader and
interface) · Motion + Tailwind (HUD) · Rive/SVG (animated icons) · Lenis optional.
One persistent WebGL canvas; do not mount/unmount scenes between transitions.

Priority: the science first (blink on real data), then the cinematography.
The effect accompanies the content, it does not cover it.

## Backend (summary; the contract is `backend/README.md`)

Base `/api/v1`. `GET /targets` (markers, coordinates already at epoch 2026.2), `GET /patches`
(the ones that open instantly), `GET /timeline?ra&dec|target&size&detector`, `GET /images/{id}.png`.
- `200` ready, `202` building (retry after `Retry-After`, show `progress`), `502` failed, `503` no DB.
- One image per epoch; all epochs of a size share `display_min/max` → the changes are real.
- Orientation: north up, east left. Images of 31/59/147 px: upscale with
  `image-rendering: pixelated`. One pixel = 6.15″; the patch center is the central pixel.
- Detector 1–6 = different bands; WISE 0855 is only visible in 6. Do not mix detectors when comparing.

Note: the original plan talked about static JSON; the real backend serves from PostgreSQL.
For the demo, preload with `python -m app.preload` (~50 min) and keep a backup video.

## Aladin Lite v3 (verified with context7, `/cds-astro/aladin-lite`)

```js
import A from "aladin-lite";           // check the npm package name before installing
A.init.then(() => {                    // WASM: always wait for A.init
  const aladin = A.aladin("#div", { target: "10.68 +41.14", fov: 8, projection: "AIT", survey: "P/DSS2/color" });
});
```
- Camera: `aladin.gotoRaDec(ra, dec)`, `aladin.animateToRaDec(ra, dec, seconds, callback?)`,
  `aladin.zoomToFoV(fovDeg, seconds, callback?)`, `aladin.setFoV(deg)` (useful for per-frame
  exponential zoom: `fov = start / Math.pow(end/start, -t)`).
- HiPS layers: `aladin.createImageSurvey(id, name, ...)` / `newImageSurvey(url)`,
  `setBaseImageLayer`, `setOverlayImageLayer(layer, name)`, `layer.setOpacity(0..1)`.
- Footprints: `A.graphicOverlay({color})` → `aladin.addOverlay(o)` → `o.addFootprints([A.polygon([[ra,dec],...])])`.
  Events: `footprintClicked`, `footprintHovered`, `objectClicked`. Coverage: `A.MOCFromURL` + `aladin.addMOC`.
- Next.js: Aladin touches `window`/WASM → load only on the client (`dynamic(..., { ssr: false })`
  or `useEffect`), single instance, clean up on unmount.
- The context7 docs have only ~305 fragments: if an API is missing, read the code on
  GitHub `cds-astro/aladin-lite` before assuming a signature.

## Science: honest limits (part of the product)

- Visible labels: "observed change" / "candidate signal". Never "Planet X found".
- Catalogued objects separate from uncatalogued movements; show the observation date and the data release from the API (`epochs[].releases`, e.g. DR1, QR3); never hard-code it.
- Decorative background stars, separated visually and programmatically from real detections.

## Conventions

- Docs: follow `AGENTS.md` → "Keeping docs in sync". Any change to endpoints, tables, the build
  pipeline, data sources, deploy or the user journey updates `docs/architecture.md` (diagrams +
  changelog) and, for data sources, `docs/data-sources.md`.
- Accessibility: respect `prefers-reduced-motion`; adjustable blink speed.
- Mobile: limit the pixel ratio and turn off postprocessing on small screens.
- Before using a library API, check context7 (Aladin, r3f, GSAP, Motion, Next.js).
- Useful skills: `gsap-core`, `gsap-timeline`, `gsap-react`, `gsap-performance`,
  `threejs-fundamentals`, `threejs-shaders`, `threejs-postprocessing`, `astropy`,
  `frontend-design`, `motion-design`, `a11y-review`. Verify the real UI with `chrome-devtools`.
- Secrets: `backend/.env` is ignored; only `.env.example` is versioned. Do not commit FITS or `data/raw/`.
- Language: all code, comments, UI text and docs are in English.

## Backend commands

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && cp .env.example .env   # fill in DATABASE_URL
python -m app.db init          # tables + catalog (idempotent)
uvicorn app.main:app --reload  # http://127.0.0.1:8000/docs
pytest                         # no network or DB needed
```
