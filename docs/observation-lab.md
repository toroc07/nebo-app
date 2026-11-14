# Observation viewer — findings

`/lab/observation` is the full-screen, interactive image viewer. It renders the synthetic export
in `shared/demo/` or, with the backend running, the real API. It is reached from the menu:
**Home → Observe → "Begin exploring"** goes straight to it, and the page has its own
"← Back to the menu" link.

## How to use it
- **Zoom switches between the three sizes.** The backend serves each observation at 3′, 6′ and
  15′. They are exact central crops of one image (same centre, same pixel scale, same epochs;
  checked in `tests/demo-palettes.test.ts`), so the viewer treats the 15′ image as the whole
  field and shows the **smallest size that covers what is on screen**: zoomed in it uses the 3′
  crop, zoomed out it loads the 15′ one. A readout next to the zoom buttons shows the zoom, the
  field of view of the screen in arcminutes and which image is in use. All sizes are preloaded,
  and the view, pin and epoch are untouched by a switch. **Because the sizes share one
  resolution, zooming into the 3′ image does not reveal more detail than the 15′ image would at
  the same zoom**; what changes is how much sky is loaded and shown. A size that fails to load
  is skipped. There is no size selector any more.
- **Starting view:** the image spans the **full width** of the screen, centred vertically. On a
  wide screen a square image is taller than the screen, so its top and bottom are cropped; pan to
  reach them. "Fit" (key `0`) returns to this view and "Whole" (key `9`) shows the entire image.
- **Infrared band / Color:** the switch in the top bar (or the `C` key) alternates between the raw
  infrared band in grey and the same band painted with a color palette (Inferno or Amber, chosen
  in the Controls panel). The swap keeps the zoom, pan, pin and epoch. SPHEREx images are a
  single infrared band, so the colors are a **display palette, not the sky's real colors**, and a
  caption under the image says so. Color exists only in the demo data for now; with the real API
  the switch shows the infrared band and Color is disabled.
- **Zoom:** mouse wheel or trackpad pinch (at the cursor), two-finger pinch on touch, double
  click, the `+` / `−` / `Fit` buttons, or the `+` `−` `0` keys.
- **Pan:** drag the image, or use the arrow keys (Shift = faster).
- **Coordinates:** hovering shows the RA/Dec under the cursor. A click (or tap) drops a **pin**
  showing RA/Dec in degrees and in h m s / ° ′ ″, plus the pixel. Drag the pin to move it; with the
  keyboard, Enter drops a pin at the centre of the view, the arrow keys move it one pixel and
  Delete removes it. The pin is stored as a sky position, so it survives epoch, size and detector
  changes. "Copy" puts `ra dec` (degrees) on the clipboard.
- **Controls panel:** object, detector, data source, color palette and the image details (data release,
  corners, brightness range, exposures, preload time).

## Changes outside the viewer's own files
`frontend/components/Nebo.tsx`: `useRouter` is imported, the "Begin exploring" tile calls
`router.push("/lab/observation")` instead of opening the Aladin sky map, and the tile and tutorial
texts describe the viewer. The sky map code (`Sky.tsx`, the "Explore" view) is untouched and still
reachable through Featured objects → field → Back. The backend was not touched.

## Pixel ↔ sky math
`lib/lab/sky.ts` needs no WCS library: the images are on a tangent-plane grid centred on the patch
position, which is the central pixel `((w-1)/2, (h-1)/2)`, at `pixel_scale_arcsec` per pixel, north
up and east left. It reproduces the API's own `expected_position` and `sector.corners` (unit tests
in `tests/sky.test.ts`). Note that under east-left the **top-left corner is NE and the top-right is
NW**.

## Viewer files

| File | What it is |
| --- | --- |
| `frontend/app/lab/observation/page.tsx` | The page |
| `frontend/app/lab/demo/[...path]/route.ts` | Serves `shared/demo/**` read-only (404 outside that folder and for file types other than json/png) |
| `frontend/components/lab/ObservationLab.tsx`, `ImageViewport.tsx`, `lab.module.css` | The viewer: HUD and the interactive image surface (unstyled beyond the basics) |
| `frontend/app/lab/demo/[...path]/route.ts` serves three folders | `/lab/demo/` → `shared/demo` (grey), `/lab/demo/amber/` → `shared/demo-color`, `/lab/demo/inferno/` → `shared/demo-inferno` |
| `frontend/lib/lab/fov.ts`, `levels.ts` | Field-of-view levels: which size to show for the visible area, and loading the three sizes |
| `frontend/lib/lab/sky.ts`, `viewport.ts` | Pixel↔sky conversion and pan/zoom math (pure, unit tested) |
| `frontend/lib/lab/contract.ts` | Full `/timeline` contract + `loadTimeline(source, …)` shared by demo and API |

To see it: `cd frontend && npm run dev` and open `/lab/observation`. The "Demo" source needs no backend.

## Verified (real browser, Next 16 dev server)
- Loads each epoch's image (31, 59 and 147 px) with `image-rendering: pixelated`; a checkerboard sits behind it so transparent pixels are visible.
- All 3 epochs preload in about 40 ms locally; blink cycles 1→2→3→1 with no loading in between.
- **`expected_position` checked against the pixels**: the brightest pixel falls at (29,30), (29,29) and (29,28) for expected positions (28.92,30.04), (28.98,29.19), (29.05,28.35). So `x,y` are **pixel centers with a 0-based index**. To draw over the image: `left% = (x + 0.5) / width_px`, `top% = (y + 0.5) / height_px`.
- Changing object and detector (3/6); each reloads the three sizes and resets playback.
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
