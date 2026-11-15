# AGENTS.md

Guide for anyone (human or AI agent) changing this repository. Project overview:
[`README.md`](README.md). How the system works: [`docs/architecture.md`](docs/architecture.md).
Claude Code also reads [`CLAUDE.md`](CLAUDE.md), which adds library notes (Aladin Lite, stack
decisions) and must stay consistent with this file.

## What this is

Nebo, a SPHEREx infrared sky viewer for the NASA Space Apps 2026 challenge "Planet X and
SPHEREx": all-sky map → field → blink between SPHEREx epochs to find real changes.

- `backend/`: FastAPI + PostgreSQL + NumPy/Astropy. Fetches SPHEREx images from NASA/IPAC
  IRSA, builds per-epoch images, serves `/api/v1`. Contract: [`backend/README.md`](backend/README.md).
- `frontend/`: Next.js 16 + TypeScript, Aladin Lite, GSAP, react-three-fiber.
  Read [`frontend/AGENTS.md`](frontend/AGENTS.md) first: this Next.js version has breaking changes.
- `shared/`: synthetic demo export. `docs/`: architecture and data sources.

## Commands

```bash
# backend
cd backend && source .venv/bin/activate
python -m app.db init            # schema + catalogue (idempotent)
uvicorn app.main:app --reload    # http://127.0.0.1:8000/docs
pytest                           # no network or DB needed
python -m app.etl run|worker     # batch builds / queue worker

# frontend
cd frontend
npm run dev                      # http://localhost:3000
npm test && npm run typecheck && npm run build
```

## Rules

- **Language**: code, comments, UI text, docs and commits in English.
- **Commits**: small, Conventional Commits (`feat:`, `fix:`, `perf:`, `docs:`...). Work on a
  branch and open a PR to `main`.
- **Verify before claiming done**: run the tests and, for behaviour changes, the real app.
  New non-trivial logic gets a test.
- **Honest science** (part of the product): UI says "observed change" / "candidate signal",
  never "Planet X found". Keep catalogued objects apart from uncatalogued movements. Show
  observation dates and data releases from the API (`epochs[].releases`), never hard-coded.
  Simulated outputs must be labelled simulated. Decorative stars stay separate from detections.
- **Science data**: never mix detectors in a comparison. All epochs of one size share
  `display_min/max`. Images are north up, east left, 6.15″/px.
- **Secrets and data**: never commit `backend/.env`, FITS files or `data/raw/`.
- **External services**: IRSA is shared by every team; keep parallel downloads modest, use
  timeouts and retries, cache responses. The browser does not call science services directly
  (except the HiPS map).
- **Accessibility**: respect `prefers-reduced-motion`; adjustable blink speed; keyboard access.

## Keeping docs in sync

Code is not done until the docs describe it. In every PR, check:

| If you change... | Update |
| --- | --- |
| An endpoint, its params, status codes or payload | `backend/README.md` (contract) and `docs/architecture.md` §3–4 |
| The build pipeline, stages, waves, caches or build modes | `docs/architecture.md` §4, §5, §7 (diagrams included) |
| A table, column or relation in `backend/db/schema.sql` | `docs/architecture.md` §6 (ER diagram and table) |
| An external data source (URL, table, collection, release, query, limits) | `docs/data-sources.md` and `docs/architecture.md` §1 |
| Deployment, Dockerfile, environment variables | `docs/architecture.md` §2 and the README quick start |
| Routes, components, the user journey or frontend data flow | `docs/architecture.md` §8 and `frontend/README.md` |
| A constant, threshold, formula or technique (pixel scale, stretch, photometry, change detection, models, retries, zoom, animation) | `docs/science-and-techniques.md` |
| What is real vs simulated | `docs/architecture.md` §9 |
| You find docs that no longer match the code | Fix them, or list them in `docs/architecture.md` §10 |

Then add one dated line to the
[architecture changelog](docs/architecture.md#architecture-changelog) describing the change in
system terms (not just "updated code").

Diagrams are Mermaid. Before pushing, render the ones you touched, for example with
`npx -y @mermaid-js/mermaid-cli -i file.mmd -o /tmp/out.svg`, or check the GitHub preview of
the PR. A broken diagram is a broken doc.
