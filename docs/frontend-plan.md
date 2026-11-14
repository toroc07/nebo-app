# Nebo — Frontend and UX/UI plan (adjusted to the real backend)

Initial design plan. Where it differs from `docs/observation-lab.md` (verified findings), the
lab document wins.

## Context
The idea in the team's Claude Docs document (a zoom journey in 3 scales + a blink comparator,
Next.js + Aladin Lite + r3f + GSAP) still stands and the stack is decided (`CLAUDE.md`, do not
re-litigate). What changed is the **backend**, which already exists and constrains the design:

| The document said | Reality (`backend/README.md`) | Design consequence |
| --- | --- | --- |
| Static JSON files | FastAPI + PostgreSQL API with `200/202/502/503` | There are real loading states: the warp screen is tied to `progress.done/total` of the `202` |
| Large cutouts | **31 / 59 / 147 px** PNGs (3′/6′/15′), 6.15″/px | The "deep field" is a pixelated mosaic: design it as an instrument (reticle, scale, `image-rendering: pixelated`), not as a photo |
| Any field | Only the **5 challenge objects** preloaded (`/targets`, `/patches`); other positions take 1–2 min | The "Region" scale centers on 5 markers; free search exists but implies waiting |
| One band | **6 detectors**, do not mix them; WISE 0855 only in 6 | The detector selector is part of the core, with a recommended one per object |
| Observation footprints | The backend does not deliver footprints; it delivers epochs (`start_utc`, `frames_used`) | Footprints come from HiPS/MOC in Aladin or are skipped in the MVP; the timeline uses the real epochs |

The official challenge page could not be read when this was written (TLS error); the plan relies
on the challenge summary in the team document and in `CLAUDE.md`. Someone on the team should
verify the judging criteria.

## Art direction (to settle with `frontend-design` + `theme-factory` before coding)
- **Concept: "observatory instrument", not a generic sci-fi dashboard.** Neutral dark sky (no purple-blue), mono/technical typography for data (dates, MJD, RA/Dec) and a humane sans for copy. A single warm accent color (amber) for what changes; everything else monochrome. Avoid glassmorphism, neon and clone cards (`design-review` audits this).
- **The change is the visual protagonist:** what moves between epochs carries the accent; what is fixed stays gray. Understanding then does not depend on being an astronomer.
- **Honesty as UI:** fixed badges "observed change" / "candidate signal", a footer with the observation date + QR2 release, decorative background marked as decorative (`aria-hidden`, programmatically distinct).

## Screen flow (3 scales, one surface)
1. **Whole sky** — Aladin with DSS/infrared HiPS; 5 `/targets` markers with a name and a one-line hook ("the star that runs the most"). Search by name/coordinates. Minimal HUD: cursor coordinates, FoV.
2. **Region** — `animateToRaDec` + `zoomToFoV` to a selected object; side panel with its card (type, note, proper motion, recommended detector) and a "See changes" button.
3. **Field (scientific core)** — the current epoch's image scaled pixelated, a **time slider** with one tick per real epoch, **blink** with adjustable speed and pause, detector 1–6 selector (with µm range and "good for"), small/medium/large size selector, a reticle with an arcmin scale and a mark on the central pixel (where the object sits). The date/epoch readout is always visible.
- **Tunnel/warp transitions and loading screen**: second priority (`CLAUDE.md`: science first, the effect accompanies). One persistent r3f canvas. With `prefers-reduced-motion` or on mobile: a simple fade.

## States to design (often forgotten)
`202` building (warp + stage `queued→querying→downloading→rendering` in plain language), `502` no coverage ("SPHEREx does not cover this position with this detector yet", with retry), `503` no DB/demo mode, empty, network error → backup video.

## Order of work (aligned to the 48 h plan)
1. Scaffold `frontend/` (Next.js + TS + Tailwind), a typed `/api/v1` client in `frontend/lib/api.ts` (types from the README contract), design tokens.
2. Scale 3 first: timeline + blink + detector on a real target (Barnard's Star, d3). This is where the challenge is won or lost.
3. Scales 1 and 2 with Aladin (loaded with `dynamic(..., { ssr: false })`, single instance) and the flight between them.
4. Tunnel/warp + a single GSAP timeline; loading tied to `progress`.
5. Known objects / candidate signals (extras), narrative mode, polish, `a11y-review`, `design-review`, demo video.

## Files and pieces (in `frontend/`)
- `app/` (layout, single page), `components/{Nebo,Sky,Field,Flight}.tsx`, `lib/api.ts`.
- Reuse: the contract in `backend/README.md`; the Aladin recipes already verified in `CLAUDE.md`; skills `frontend-design`, `theme-factory`, `motion-design`, `gsap-*`, `a11y-review`.

## Verification
- Local backend (`uvicorn`) + the backend `pytest` untouched; frontend against the real API with a preloaded target.
- `chrome-devtools`: full sky→field flow, blink at different speeds, 202/502 states, mobile (emulate), `lighthouse_audit`, console free of errors.
- `a11y-review` (contrast, keyboard on the slider, `prefers-reduced-motion`) and `design-review` against the "AI look".

## Open decisions (recommendation in parentheses)
- Final product name (keep "Nebo").
- SPHEREx footprints in the MVP? (No: use target markers; footprints only if time allows).
- UI language (English).
