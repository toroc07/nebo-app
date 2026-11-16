# Docs

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | How the whole system works: deployment, backend, build pipeline, database, frontend, real vs simulated data, changelog. Start here |
| [data-sources.md](data-sources.md) | Every external data source (NASA/IPAC IRSA SPHEREx and CatWISE2020, ESA Gaia DR3, their GAVO and NOIRLab mirrors, SIMBAD-derived coordinates), the challenge resources and how they are used |
| [science-and-techniques.md](science-and-techniques.md) | Every physical quantity, constant, threshold, metric and technique the app uses (pixel scale, bands, epochs, stretch, photometry, change detection, models, retries, zoom, warp) and why |
| [position-validation.md](position-validation.md) | Generated report: measured vs expected (proper-motion) position of the 5 catalogue targets in every epoch, from `python -m app.position_report` |
| [frontend-plan.md](frontend-plan.md) | Early UX plan and art direction for the frontend |
| [observation-lab.md](observation-lab.md) | Findings of the removed `/lab/observation` viewer; its pixel↔sky math still drives `lib/lab/sky.ts` |

Backend API contract: [`backend/README.md`](../backend/README.md). Frontend setup:
[`frontend/README.md`](../frontend/README.md). Rules for keeping these docs in sync:
[`AGENTS.md`](../AGENTS.md#keeping-docs-in-sync).
