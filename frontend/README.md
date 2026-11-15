# Nebo frontend

Observation menu with a ground-level landscape, an Aladin sky map and time comparison of SPHEREx images.

Requires Node.js 20.9+.

```bash
npm ci
npm run dev
```

Open http://localhost:3000. The backend is expected at http://127.0.0.1:8000. To change it, create `.env.local` with `NEXT_PUBLIC_API_ORIGIN=https://your-api.example` and restart Next.js. In a deployment, use a public HTTPS URL reachable from the browser, and set the allowed origin in the backend as well.

The catalog and the images require the backend with PostgreSQL configured and data available. The start screen and its tutorial work without the API (the tutorial screenshots live in `public/tutorial/`; retake them and update the callout positions in `components/TutorialTour.tsx` if the UI changes); service errors are shown where the data would be. No fictitious scientific images are included. The sky map is the SPHEREx all-sky HiPS from NASA/IPAC IRSA; the comparison cutouts come from SPHEREx too.

```bash
npm test
npm run typecheck
npm run build
```

The sky explorer has a public chat (top-left key): one room per catalogue object, or a general room when nothing is selected. Nobody signs in; the browser keeps a generated nickname (`nebo.chat.nickname` in localStorage). The backend filters every message and deletes it after 24 hours (contract in `backend/README.md`).

In the observation room, the wall tablet shows the observed object as a spinning 3D model (`components/StarHologram.tsx`). It is an illustration from the object's type and temperature, not SPHEREx data, and it says so on screen.

Playback starts paused and stops when the tab is hidden; the blink speed is chosen in the field console. The system reduced-motion setting turns off every animation. Searches use ICRS degrees, and the viewer keeps the detector across epochs.

The landscape is a decorative image generated for Nebo. The Barlow Condensed and IBM Plex fonts are served locally; their OFL licenses are included in `public/fonts`.

To repeat the browser flows on Linux with Chrome installed:

```bash
npm run build
npm run start -- --port 3001
# In another terminal:
node tests/browser.mjs
```

The tests intercept the API and save results and screenshots to `artifacts/nebo` in the workspace. For another URL use `NEBO_TEST_URL`. The report for this session is in `artifacts/nebo/verification.md`.

## Field links

`/?ra=133.795&dec=-7.245&fov=6&det=6` (or `/?target=wise-0855`) skips the menu and the map and
opens that field in the viewer. `ra`/`dec` are ICRS degrees; `fov` is 3, 6 or 15 arcminutes
(default 6); `det` is 1–6 (`detector` also works; default: the object's recommended detector,
else 3); `epoch` is 1-based like the viewer (default 1, clamped to the last one). Any invalid value
ignores the whole link and the app starts at Home. Coordinates within 30″ of a catalogued object open that object's field
and show its name and type (from `patch.target` in `/timeline`), whether they come from a link,
the RA/Dec form or the map centre. "Copy link" in the viewer writes the current
field as such a link; a field that is not cached shows the usual building screen. A coordinate
link may carry `name` (≤ 80 characters, e.g. `&name=Proxima+Centauri`): the viewer shows it as the
title and object name for a field that is not in the catalogue. Catalogue targets ignore it.

## Field viewer layers

`components/Field.tsx` draws catalog layers over the field image with `components/FieldOverlays.tsx`
(helpers and types in `lib/overlays.ts`, Gaia in `lib/lab/gaia.ts`). Each layer is off by default and
fetched the first time it is switched on (right column, above the cards):

- **Gaia DR3** (`/patches/{id}/gaia`): green rings, magenta for fast movers (≥ 100 mas/yr) with a
  dashed first→last epoch trajectory. Stars are propagated to each epoch's `mid_mjd`, so they move
  with the slider and the blink.
- **CatWISE** (`/patches/{id}/wise`): amber diamonds; sources with no Gaia counterpart and red
  W1−W2 are dashed pink rings ("cold candidate"), which pulse unless reduced motion is on.
- **Changes** (`/patches/{id}/candidates`, first vs last epoch, read from `classification`):
  badges "Catalogued object", "Candidate signal" or "Cold candidate (no Gaia)". Cold candidates and
  the strongest changes (8 in total) get a text badge; the rest are clickable dots.
- **Alignment** (top-right of the image, `/patches/{id}/alignment`): per-epoch offset against slow
  Gaia stars. "Simulate an offset" shifts the last epoch by 2 px to show the warning; the banner
  always says "Simulation".

A status line under the switches says what each active layer holds, or why it is empty
("the archive did not answer", "no sources returned", "not available for this field yet"); a
failed switch turns amber. Clicking a marker or badge fills the "Selected source" card (distance in pc and light-years,
brightness, proper motion, colour, status). "Suggested in Explore" (`/explore/suggested`) lists
nearby or fast Gaia stars around the field as named links to their own field, tagged "opens
instantly" (a preloaded patch within 30″ for this detector, from `/patches`) or "new download ·
1–3 min".

## Observation viewer

`/lab/observation` (opened by URL) is a full-screen viewer of the SPHEREx epochs. Zoom with
the wheel or a pinch, drag to pan, click to drop a pin that shows RA/Dec (draggable), and use the
slider or Blink to compare epochs. Zooming switches automatically between the 3′, 6′ and 15′ images the backend serves (they are central crops of one image). The image starts at the full screen width, and the top-bar switch (or the `C` key) alternates between the grey infrared band and a color palette (demo data only; the colors are a display palette, not the sky's real colors). By default it reads the real API; the Controls panel (or the error
message) can switch to the synthetic export in `shared/demo/`, which works without a backend. Details and the types
`lib/api.ts` still lacks are in `docs/observation-lab.md`. `tests/browser.mjs` needs `shared/demo`
next to the frontend folder.
