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

## Observation lab

`/lab/observation` (Home → Observe → "Image lab") renders the synthetic export in `shared/demo/` or the real API, so the viewer can be tested without a backend. Findings and the types `lib/api.ts` still lacks are in `docs/observation-lab.md`.
