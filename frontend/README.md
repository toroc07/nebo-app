# Nebo frontend

Observation menu with a ground-level landscape, an Aladin sky map and time comparison of SPHEREx images.

Requires Node.js 20.9+.

```bash
npm ci
npm run dev
```

Open http://localhost:3000. The backend is expected at http://127.0.0.1:8000. To change it, create `.env.local` with `NEXT_PUBLIC_API_ORIGIN=https://your-api.example` and restart Next.js. In a deployment, use a public HTTPS URL reachable from the browser, and set the allowed origin in the backend as well.

The catalog and the images require the backend with PostgreSQL configured and data available. The start screen and its tutorial work without the API; service errors are shown where the data would be. No fictitious scientific images are included. The sky map is the SPHEREx all-sky HiPS from NASA/IPAC IRSA; the comparison cutouts come from SPHEREx too.

```bash
npm test
npm run typecheck
npm run build
```

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

## Observation viewer

`/lab/observation` (opened by URL) is a full-screen viewer of the SPHEREx epochs. Zoom with
the wheel or a pinch, drag to pan, click to drop a pin that shows RA/Dec (draggable), and use the
slider or Blink to compare epochs. Zooming switches automatically between the 3′, 6′ and 15′ images the backend serves (they are central crops of one image). The image starts at the full screen width, and the top-bar switch (or the `C` key) alternates between the grey infrared band and a color palette (demo data only; the colors are a display palette, not the sky's real colors). By default it reads the real API; the Controls panel (or the error
message) can switch to the synthetic export in `shared/demo/`, which works without a backend. Details and the types
`lib/api.ts` still lacks are in `docs/observation-lab.md`. `tests/browser.mjs` needs `shared/demo`
next to the frontend folder.
