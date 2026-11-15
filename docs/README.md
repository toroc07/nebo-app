# Docs

| Document | What it covers |
| --- | --- |
| [architecture.md](architecture.md) | How the whole system works: deployment, backend, build pipeline, database, frontend, real vs simulated data, changelog. Start here |
| [data-sources.md](data-sources.md) | Every external data source (NASA/IPAC IRSA SPHEREx, ESA Gaia DR3), the challenge resources and how they are used |
| [science-and-techniques.md](science-and-techniques.md) | Every physical quantity, constant, threshold, metric and technique the app uses (pixel scale, bands, epochs, stretch, photometry, change detection, models, retries, zoom, warp) and why |
| [frontend-plan.md](frontend-plan.md) | Early UX plan and art direction for the frontend |
| [observation-lab.md](observation-lab.md) | Notes on the `/lab/observation` viewer (some navigation details are out of date, see architecture §10) |

Backend API contract: [`backend/README.md`](../backend/README.md). Frontend setup:
[`frontend/README.md`](../frontend/README.md). Rules for keeping these docs in sync:
[`AGENTS.md`](../AGENTS.md#keeping-docs-in-sync).
