# Nebo frontend

Observation menu with a ground-level landscape, an Aladin sky map and time comparison of SPHEREx images.

Requires Node.js 20.9+.

```bash
npm ci
npm run dev
```

Open http://localhost:3000. The backend is expected at http://127.0.0.1:8000. To change it, create `.env.local` with `NEXT_PUBLIC_API_ORIGIN=https://your-api.example` and restart Next.js. In a deployment, use a public HTTPS URL reachable from the browser, and set the allowed origin in the backend as well.

The catalog and the images require the backend with PostgreSQL configured and data available. The menu, tutorial and settings work without the API; service errors are shown where the data would be. No fictitious scientific images are included. DSS2 is a visible reference map; the comparison cutouts come from SPHEREx.

```bash
npm test
npm run typecheck
npm run build
```

The sky explorer has a public chat (top-left key): one room per catalogue object, or a general room when nothing is selected. Nobody signs in; the browser keeps a generated nickname (`nebo.chat.nickname` in localStorage). The backend filters every message and deletes it after 24 hours (contract in `backend/README.md`).

Display settings are stored only in localStorage. Playback starts paused and stops when the tab is hidden. The system reduced-motion setting takes priority. Searches use ICRS degrees, and the viewer keeps the detector across epochs.

The landscape is a decorative image generated for Nebo. The Barlow Condensed and IBM Plex fonts are served locally; their OFL licenses are included in `public/fonts`.

To repeat the browser flows on Linux with Chrome installed:

```bash
npm run build
npm run start -- --port 3001
# In another terminal:
node tests/browser.mjs
```

The tests intercept the API and save results and screenshots to `artifacts/nebo` in the workspace. For another URL use `NEBO_TEST_URL`. The report for this session is in `artifacts/nebo/verification.md`.

## Observation viewer

"Begin exploring" opens `/lab/observation`: a full-screen viewer of the SPHEREx epochs. Zoom with
the wheel or a pinch, drag to pan, click to drop a pin that shows RA/Dec (draggable), and use the
slider or Blink to compare epochs. Zooming switches automatically between the 3′, 6′ and 15′ images the backend serves (they are central crops of one image). The image starts at the full screen width, and the top-bar switch (or the `C` key) alternates between the grey infrared band and a color palette (demo data only; the colors are a display palette, not the sky's real colors). By default it renders the synthetic export in `shared/demo/`, so
it works without a backend; switch to the real API in the Controls panel. Details and the types
`lib/api.ts` still lacks are in `docs/observation-lab.md`. `tests/browser.mjs` needs `shared/demo`
next to the frontend folder.
