# Nebo backend

API for the Nebo planetarium. For any patch of sky it returns the **timeline of SPHEREx
images**: one image per survey epoch (SPHEREx maps the whole sky every ~6 months), per
detector (1-6) and per display size. Images are downloaded from NASA/IPAC IRSA, processed
once and stored in PostgreSQL, so the frontend gets them instantly afterwards.

## How it works

1. The frontend asks for a patch (`ra`/`dec` or a catalogue `target`), a detector and a size.
2. If the timeline is in the database, the API answers `200` with the image URLs.
3. If not, the API answers `202` and builds it in the background:
   - lists the SPHEREx exposures that cover the patch (IRSA TAP),
   - downloads a cutout of up to 8 exposures per epoch (IRSA is slow: 1-2 minutes in total),
   - subtracts the zodiacal light, reprojects every exposure to a common **north-up,
     east-left** grid and co-adds each epoch,
   - renders a PNG per epoch for the three sizes and stores everything in PostgreSQL.

   The frontend calls again after `Retry-After` seconds and shows the progress meanwhile.

A request within 30 arcsec of an existing patch reuses it. Each patch is downloaded once at
the largest size; the other sizes are central crops, so switching size is instant.

## Setup

Requires Python 3.12.

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # then fill in DATABASE_URL
```

### Database

The API needs a PostgreSQL 14+ database. Until `DATABASE_URL` is set in `backend/.env`, every
data endpoint answers `503` with `{"code": "database_not_configured"}`.

Set up a new database once (creates the tables and seeds the catalogue). It is safe to run
again:

```bash
python -m app.db init
```

The schema is in [db/schema.sql](db/schema.sql) if you prefer to apply it with `psql`.

| Table | Content |
| --- | --- |
| `targets` | Catalogue objects shown as markers (the 5 challenge objects) |
| `patches` | Sky positions that have been requested |
| `timelines` | One per patch and detector: `building` / `ready` / `failed` and build progress |
| `timeline_images` | One PNG (`bytea`) per timeline, epoch and size, with its metadata |

### Run

```bash
uvicorn app.main:app --reload          # http://127.0.0.1:8000, docs at /docs
```

### Preload the catalogue

Builds the 5 challenge objects for all 6 detectors so the demo opens instantly. It is safe to
re-run, because ready timelines are skipped. Expect about 50 minutes when IRSA responds well.

```bash
python -m app.preload
python -m app.preload --targets wise-0855,eps-indi-b --detectors 5,6
```

## API reference

Base path: `/api/v1`. Interactive docs: `http://127.0.0.1:8000/docs`.

### `GET /health`

```json
{ "status": "ok", "database": "ok" }
```

`database` is `ok`, `not_configured` or `unreachable`.

### `GET /targets`

Catalogue objects for the planetarium markers. Coordinates are already propagated to epoch
2026.2: fast movers like Barnard's Star are arcminutes away from their J2000 positions.

```json
[
  {
    "slug": "barnards-star", "name": "Barnard's Star", "ra": 269.446223, "dec": 4.76878,
    "kind": "high_proper_motion_star", "note": "...",
    "pm_ra_mas_yr": -801.6, "pm_dec_mas_yr": 10362.4, "recommended_detector": 3
  }
]
```

### `GET /patches`

Patches that already have at least one ready timeline (they open instantly).

```json
[{ "id": 1, "ra": 269.446223, "dec": 4.76878, "target_slug": "barnards-star", "detectors_ready": [3, 6] }]
```

### `GET /timeline`

| Parameter | Values | Default |
| --- | --- | --- |
| `ra`, `dec` | ICRS degrees (`0 <= ra < 360`, `-90 <= dec <= 90`) | — |
| `target` | catalogue slug, instead of `ra`/`dec` | — |
| `size` | `small` (3′), `medium` (6′), `large` (15′) | `medium` |
| `detector` | `1`-`6` | the target's `recommended_detector`, else `3` |

Give either `target` or both `ra` and `dec`.

| Detector | Wavelengths (µm) | Good for |
| --- | --- | --- |
| 1 | 0.75 – 1.09 | Stars |
| 2 | 1.10 – 1.62 | Stars, red dwarfs |
| 3 | 1.63 – 2.41 | Stars, red dwarfs, variable stars |
| 4 | 2.42 – 3.82 | Young stars with dusty disks |
| 5 | 3.83 – 4.41 | Cold brown dwarfs |
| 6 | 4.42 – 5.00 | Coldest brown dwarfs (WISE 0855 is only visible here) |

**`200` — ready**

```json
{
  "status": "ready",
  "patch": { "id": 1, "ra": 269.446223, "dec": 4.76878, "target": "barnards-star" },
  "detector": { "id": 3, "bandpass": "SPHEREx-D3", "wavelength_range_um": [1.63, 2.41] },
  "size": { "name": "medium", "side_deg": 0.1, "side_arcmin": 6.0, "width_px": 59, "height_px": 59, "pixel_scale_arcsec": 6.15 },
  "orientation": "north_up_east_left",
  "display": { "stretch": "asinh", "unit": "MJy/sr", "note": "..." },
  "epochs": [
    {
      "index": 0,
      "start_utc": "2025-08-15T20:45:11+00:00", "end_utc": "2025-08-27T11:37:04+00:00",
      "mid_mjd": 60908.00667, "frames_available": 18, "frames_used": 8,
      "display_min": 0.16, "display_max": 14.05,
      "image_url": "/api/v1/images/42.png"
    }
  ],
  "frames_found": 59, "frames_used": 24,
  "updated_at": "2026-11-14T15:02:11+00:00"
}
```

**`202` — building**: call again after the `Retry-After` header (seconds).

```json
{
  "status": "building",
  "patch": { "id": 7, "ra": 10.0, "dec": 20.0, "target": null },
  "detector": { "id": 3, "bandpass": "SPHEREx-D3", "wavelength_range_um": [1.63, 2.41] },
  "progress": { "stage": "downloading", "done": 11, "total": 24 },
  "retry_after_s": 5
}
```

`stage` goes `queued` → `querying` → `downloading` → `rendering`.

**`502` — failed**: `{"status": "failed", ..., "error": "No SPHEREx images cover this position with this detector yet."}`.
The same request is retried automatically after one minute.

Other answers: `404` for an unknown target, `422` for invalid parameters, `503` when the
database is not configured.

### `GET /images/{id}.png`

The processed image: 8-bit greyscale with an alpha channel, where pixels without data are
transparent. Row 0 is north, and east is on the left. Ids change when a timeline is rebuilt,
so responses are cached for a year (`immutable`).

## Notes for the frontend

- Show the epochs in order as a blink animation. All epochs of one size share the same
  brightness scale (`display_min`/`display_max`), so changes are real, not display artefacts.
- Very bright stars saturate SPHEREx. Their cores are kept visible: small holes fully
  surrounded by data are filled with the brightest pixel around them (display only).
- The images are small (31, 59 or 147 px). Scale them up with
  `image-rendering: pixelated` to keep the pixels sharp.
- The patch centre is the image's central pixel, and one pixel is 6.15 arcsec, which is
  enough to place overlays.
- `GET /timeline` creates the patch on first use, so the first request for a new position
  answers `202`.

## Tests

```bash
pytest
```

The tests use synthetic FITS files and an in-memory store, so they need neither network nor
database. The `PostgresStore` tests run only when `NEBO_TEST_DATABASE_URL` points to a
throwaway database.

If VS Code reports `Import "fastapi" could not be resolved`, select the interpreter
`backend/.venv` (*Python: Select Interpreter*).
