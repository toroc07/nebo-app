# Observation lab — findings

Test route `/lab/observation` to see how the images in `shared/demo/` (synthetic) are consumed
and, with the backend running, the real API. It is reached from the menu:
**Home → Observe → "Image lab (demo, no backend)"**, and the page has its own
"← Back to the menu" link.

**Only change in a file outside the lab:** one new block in `frontend/components/Nebo.tsx`,
right before `{view === "Coordinates" && (`: a `<p><a className="secondary" href="/lab/observation">`
shown only in the "Observe" view. It does not touch the grid, the state or the CSS. To remove
the entry point, delete that block. The backend was not touched.

## Lab files (all new, removable with no effect on the menu)

| File | What it is |
| --- | --- |
| `frontend/app/lab/observation/page.tsx` | The page |
| `frontend/app/lab/demo/[...path]/route.ts` | Serves `shared/demo/**` read-only (404 outside that folder and for file types other than json/png) |
| `frontend/components/lab/ObservationLab.tsx`, `lab.module.css` | Basic viewer, unstyled |
| `frontend/lib/lab/contract.ts` | Full `/timeline` contract + `loadTimeline(source, …)` shared by demo and API |

To see it: `cd frontend && npm run dev` and open `/lab/observation`. The "Demo" source needs no backend.

## Verified (real browser, Next 16 dev server)
- Loads each epoch's image (31, 59 and 147 px) with `image-rendering: pixelated`; a checkerboard sits behind it so transparent pixels are visible.
- All 3 epochs preload in about 40 ms locally; blink cycles 1→2→3→1 with no loading in between.
- **`expected_position` checked against the pixels**: the brightest pixel falls at (29,30), (29,29) and (29,28) for expected positions (28.92,30.04), (28.98,29.19), (29.05,28.35). So `x,y` are **pixel centers with a 0-based index**. To draw over the image: `left% = (x + 0.5) / width_px`, `top% = (y + 0.5) / height_px`.
- Changing object, detector (3/6) and size; each requests its own timeline and resets playback.
- "Real API" source with the backend off: a readable error message, the page does not break.

## For Codex (not touched)
1. **`lib/api.ts` omits fields the backend already sends.** Type snippet (see `lib/lab/contract.ts` for the full one):
   ```ts
   export type Epoch = {
     // …existing fields…
     mid_mjd: number; frames_available: number;
     display_min: number; display_max: number;
     releases: string[];
     expected_position?: { ra: number; dec: number; x: number; y: number; in_image: boolean };
   };
   export type Timeline = {
     // …existing fields…
     sector?: { center: { ra: number; dec: number };
                corners: Record<"NW" | "NE" | "SE" | "SW", [number, number]> };
     data?: { source: string; processed_at: string };
     display: { stretch: string; unit: string; note: string };
   };
   ```
2. **`Field.tsx` hard-codes "SPHEREx QR2".** The data carries `releases` (today `["qr2"]`); it should show that, and warn if the epochs mix releases.
3. **`Field.tsx` swaps `<img src>` without preloading.** Locally it is not noticeable; on a real network each epoch may flicker as it arrives. Recommendation: preload every epoch (`new Image()`) and enable "Compare epochs" only when they finish (the lab shows the pattern).
4. `Field.tsx` does not yet use `expected_position` (object marker and trail) or `sector.corners` (to place the cutout over Aladin).
5. To try `Field` without a backend: `loadTimeline(source, …)` in `lib/lab/contract.ts` already unifies demo and API; it would be enough to change the origin.

## Next 16 / Turbopack trap
A route handler that reads files **outside** the project (`../shared/demo`) made Turbopack trace the whole repo, and every read triggered a recompile and an endless page reload. It is fixed by marking `process.cwd()` with `/* turbopackIgnore: true */` (already applied in the lab's route handler). Remember it if anyone else serves files from `shared/`.

## Demo limits
No `diff` images, no `202 building` responses (the lab's progress state is only exercised with the real API), only 3 epochs and detectors 3 and 6; brightness and noise are made up, so do not judge contrast by them.

## Pending from the backend (nothing blocking)
- Confirm that `expected_position` also arrives in the real API for positions that are not a target (it is optional in the type here).
- With the real API running, repeat the preload test to measure the real image time.
