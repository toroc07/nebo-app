# Nebo backend

API for the Nebo planetarium. For any patch of sky it returns the **timeline of SPHEREx
images**: one image per survey epoch (SPHEREx maps the whole sky every ~6 months), per
detector (1-6) and per display size. Images are downloaded from NASA/IPAC IRSA, processed
once and stored in PostgreSQL, so the frontend gets them instantly afterwards.

## How it works

1. The frontend asks for a patch (`ra`/`dec` or a catalogue `target`), a detector and a size.
2. If the timeline is in the database, the API answers `200` with the image URLs.
3. If not, the API answers `202` and builds it in the background:
   - lists the SPHEREx exposures that cover the patch (IRSA TAP; when TAP is down, IRSA SIA,
     which lags about one day),
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

### ETL pipeline (real IRSA data -> database)

`python -m app.etl` downloads real SPHEREx images from IRSA, processes them and writes the
result to the database in `DATABASE_URL`. Nothing is synthetic. Ready timelines are skipped,
so it is safe to re-run. IRSA is slow: a new field takes 1-2 minutes per detector.

```bash
python -m app.etl run                                           # catalogue, detectors 1-6 (~50 min)
python -m app.etl run --targets wise-0855,eps-indi-b --detectors 5,6
python -m app.etl run --coords "269.4,4.77;133.76,-7.24" --detectors 3
python -m app.etl run --file fields.csv                         # one "ra,dec" per line
```

`python -m app.preload` is an alias of `etl run`.

**Worker mode.** By default (`NEBO_BUILD_MODE=inline`) the API builds a missing field in its own
threads. On platforms that throttle CPU between requests (Cloud Run) set
`NEBO_BUILD_MODE=queue` on the API: it then only queues the field and answers `202`, and a
separate process builds it:

```bash
python -m app.etl worker            # loops until stopped; --once exits when the queue is empty
```

Run one worker per instance of the same image (`python -m app.etl worker` as the command). A
worker that dies mid-build is recovered automatically: after `STALE_BUILD_S` (15 min) the next
request for that field queues it again. Never commit `DATABASE_URL`: it belongs in `backend/.env`.

**Cloud Run memory.** Cloud Run keeps the container disk in RAM, and the cutout cache on disk
only grows (about 4 MB per cutout, ~2000 for the whole catalogue), so a long `etl run` ends in an
out-of-memory kill. Set `NEBO_DISK_CACHE=0` on the API and on every ETL job there; the GCS cache
(when its bucket is configured) still avoids downloading a cutout twice. 2 GiB of memory is enough
for a job that builds one timeline at a time.

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
  "is_partial": true,
  "preview_image_url": "/api/v1/images/41.png",
  "progress": { "stage": "downloading", "done": 11, "total": 24, "epochs_ready": 0, "is_partial": true },
  "retry_after_s": 2
}
```

`stage` goes `queued` → `querying` → `downloading` → `first_light` → `preview_ready` →
`refining` → `rendering`. Coordinate searches build in steps: `first_light` is one frame,
`preview_ready` is one frame per epoch (enough to blink), `refining` adds the remaining frames.
`epochs[]` of a `202` already lists the epochs rendered so far (it grows during the build).
`Retry-After` is 2 s in the early stages (up to `first_light`) and 5 s afterwards; use it
instead of a fixed interval.
When IRSA itself is down, the build goes `querying` → `waiting_for_archive` (`progress.done` =
attempt) → `querying` and retries with a 15 → 30 → 60 s backoff for up to `NEBO_ARCHIVE_WAIT_S`
(default 300 s). Only then does it fail with `502` `code: "archive_unavailable"`.

**Early preview (`wait_for`)**: `GET /timeline?...&wait_for=first_light` (or `preview`) does not
wait; it answers `200` with `"is_partial": true, "refining": true` as soon as a preview image
exists (`first_light`, or `preview_ready` for `preview`), and `202` before that. Keep polling
after `Retry-After`: the images are replaced at each step and **their ids change**, so re-read
`image_url` every time. The final answer is a normal `200` without `is_partial`. Coordinate
searches only; label partial images as preliminary.

**`502` — failed**: `{"status": "failed", ..., "code": "build_failed", "error": "No SPHEREx images cover this position with this detector yet."}`.
`code: "archive_unavailable"` when IRSA itself did not answer (TAP and SIA both failed): retry later.
The same request is retried automatically after one minute.

Other answers: `404` for an unknown target, `422` for invalid parameters, `503` when the
database is not configured.

### `GET /images/{id}.png`

The processed image: 8-bit greyscale with an alpha channel, where pixels without data are
transparent. Row 0 is north, and east is on the left. Ids change when a timeline is rebuilt,
so responses are cached for a year (`immutable`).

### `GET /patches/{id}/gaia?size=medium&mjd=<mid_mjd>&mjd=<mid_mjd>...`

Catalogued Gaia DR3 stars on the patch image, to tell known objects from uncatalogued changes.
Pass one `mjd` per epoch (its `mid_mjd`, up to 50); `stars[].positions[i]` matches `mjd[i]`.
Gaia positions (J2016.0) are propagated with their proper motion to each date; parallax is
ignored. Pixels use the PNG grid of that `size` (row 0 north, east left). Optional
`g_max` (default 18) is the faintest G magnitude asked for; the brightest 5000 stars are kept.
In dense fields (galactic plane) that limit is hit: `catalog.truncated` is `true` and
`catalog.g_complete` is the magnitude down to which the list is complete (otherwise it equals
`g_max`). Say "no Gaia star brighter than G = g_complete", never "uncatalogued" without it.
The cone query is cached in `api_query_cache`.

```json
{
  "patch_id": 1,
  "size": {"name": "medium", "width_px": 59, "height_px": 59},
  "catalog": {"name": "Gaia DR3", "ref_epoch": 2016.0, "g_max": 18.0, "g_complete": 18.0,
              "radius_deg": 0.22678, "truncated": false, "note": "..."},
  "mjd": [60914.2, 61110.4],
  "stars": [{
    "source_id": "4472832130114786688", "g_mag": 8.194, "bp_rp": 2.835,
    "pm_ra_mas_yr": -801.551, "pm_dec_mas_yr": 10362.394, "pm_total_mas_yr": 10393.35,
    "parallax_mas": 546.976, "distance_pc": 1.83,
    "positions": [{"mjd": 60914.2, "ra": 269.4462, "dec": 4.7687, "x": 29.1, "y": 29.4, "in_image": true}]
  }]
}
```

`pm_*`, `parallax_mas`, `distance_pc` and `bp_rp` can be `null` (Gaia has no full solution for
that star). Cold brown dwarfs such as WISE 0855 and Eps Indi B are not in Gaia: an infrared
source with no Gaia star on it is expected for them. `502` with `code: "gaia_unavailable"` when
the ESA archive does not answer (retry after `Retry-After`); `404` for an unknown patch.

### `GET /patches/{id}/wise?size=medium&mjd=<mid_mjd>...`

Catalogued **CatWISE2020** infrared sources (3.4 um W1, 4.6 um W2) on the patch image, propagated
from epoch 2015.4 to each requested `mjd` and cross-matched against Gaia DR3 (`crossmatch_gaia=true`).
Sources with no Gaia match within `gaia_match_radius_arcsec` (default `3.0"`) and
`W1 - W2 >= cold_w1_w2_min` (default `1.0`) are flagged `cold_candidate: true`. `catalog.gaia_complete_to_g`
reports the Gaia completeness limit used for the cross-match. Returns `502` (`code: "wise_unavailable"`)
when IRSA CatWISE2020 does not answer.

### `GET /patches/{id}/candidates?detector=3&size=medium&epoch_a=0&epoch_b=<last>&snr_threshold=4.0`

Detects significant point-like changes in `epoch_b - epoch_a` using the float32 `.npz` arrays,
cross-matches each peak against Gaia DR3 (at both epochs) and CatWISE2020, and labels each as
`"catalogued_object"` or `"candidate_signal"` (along with `gaia_complete_to_g`). Returns `404` if
the timeline or `.npz` arrays are not ready.

### `GET /patches/{id}/alignment?detector=3&size=medium`

Checks astrometric alignment per epoch against slow Gaia DR3 reference stars (`pm_total <= 20 mas/yr`),
returning `stars_used`, `median_dx_px`, `median_dy_px`, `rms_arcsec`, and `status`
(`"ok"`, `"offset_warning"`, or `"insufficient_stars"`).

### `GET /explore/suggested?ra=<deg>&dec=<deg>&radius_deg=30&limit=12`

Returns nearby (`parallax > 50 mas`) or fast-moving (`pm > 500 mas/yr`) Gaia DR3 stars propagated
to epoch 2026.2 for the sky explorer, cached in `api_query_cache` with a curated fallback if ESA
Gaia TAP is unavailable.

### `GET /patches/{id}/spectrum?epoch_index=-1` and `GET /patches/{id}/metrics?detector=3`

Simulated science profiles (`simulated: true`). Fields the web client reads (keep them stable;
`frontend/tests/fixtures/science-responses.json` holds a real answer):
- `/spectrum`: `channels[]` of `{channel_id, band, lambda_c_um, flux_mjy, sigma_mjy, is_blankch}`
  (102 entries, derived from the stored columnar arrays; BLANKCH 51-52 and invalid channels have
  `flux_mjy: null`, never 0), plus `indices[]` (`index_code, value, uncertainty, snr,
  is_significant_3s`).
- `/metrics`: `confidence.c_global` (0-100) with `s_snr, s_dipole, s_flags, s_psf`; `variability`
  (`chi2_var_reduced, stetson_j, von_neumann_eta, lomb_scargle_power, is_variable`);
  `image_photometry[]` measured on the patch's float32 arrays (moving targets at their
  proper-motion position for each epoch). `snr` uses the measured `sigma_stat`;
  `sigma_reported` adds the 3% floor. Fields are `null` when the epoch has no usable variance.
- `/models/event`: `treeshap_values.top_drivers[]` of `{feature, phi}`.

### Database catalog hydration (`python -m app.db sync-catalogs`)

Hydrates `targets.gaia_*` and `targets.wise_*` columns (and updates proper-motion-propagated
coordinates for optical targets while keeping SIMBAD/CatWISE fallback for cold brown dwarfs). Can
also be run via `python -m app.db init --sync-catalogs`.

### Public chat: `GET` / `POST /chat/{room}/messages`

One room per catalogue object (`room` = its slug) plus `general`. Anonymous: the browser
generates the nickname (`Stargazer-4821`, words in `app/chat.py`) and the server accepts no other
shape. Messages are deleted after 24 hours and nothing about the sender is stored.

- `GET ?after=<id>`: messages oldest first; without `after`, the latest 50. Poll with the last
  id received (the web polls every 3 s while the chat is open).
  `{"room", "retention_hours": 24, "max_length": 280, "messages": [{id, nickname, body, created_at}]}`
- `POST {"nickname": "Nova-0001", "body": "..."}`: `201` with the stored message.
  `422 {"code", "detail"}` when refused: `blocked_words` (Spanish and English, also with digits,
  symbols, stretched or spaced letters), `personal_data` (links, emails, @handles, phone
  numbers), `too_long`, `empty` or `nickname`. `429` + `Retry-After` for more than one message
  every 3 s from the same address (kept in memory only). `404` for an unknown room.

## Notes for the frontend

- Show the epochs in order as a blink animation. All epochs and all sizes share the
  same brightness scale (`display_min`/`display_max`, taken from the largest size), so
  changes are real, not display artefacts. Epochs with fewer exposures (`frames_used`) are
  noisier; show that number.
- Very bright stars saturate SPHEREx. Their cores are kept visible: small holes fully
  surrounded by data are filled with the brightest pixel around them (display only).
- The images are small (31, 59 or 147 px). Scale them up with
  `image-rendering: pixelated` to keep the pixels sharp.
- The patch centre is the image's central pixel, and one pixel is 6.15 arcsec, which is
  enough to place overlays.
- `GET /timeline` creates the patch on first use, so the first request for a new position
  answers `202`.

## For the frontend: extra fields, diff and static export

`GET /timeline` (ready) also returns:

- `sector`: `center` and `corners` (`NW`, `NE`, `SE`, `SW`) of the image in ICRS degrees.
- `data`: `source` and `processed_at` (when the timeline was built).
- per epoch: `releases` (data release of its exposures, e.g. `["qr2"]`) and
  `expected_position`: `{ra, dec, x, y, in_image}` from the catalogue proper motion at the
  epoch's mid time, or `null` for objects outside the catalogue. `x`/`y` are PNG pixels
  (origin top-left, pixel centres at integers).

`GET /timeline/diff?a=0&b=1` (same `ra`/`dec`/`target`, `size`, `detector` as `/timeline`):
PNG of epoch `b` minus epoch `a`. Red = brighter in `b`, blue = fainter, black = unchanged,
transparent = no data. Header `X-Diff-Limit` is the brightness (MJy/sr) at full colour. The
timeline must be ready (otherwise `404`); it never starts a build. Uses the float32 arrays.

`GET /timeline/rgb?r=6&g=3&b=1&epoch=0` (same `ra`/`dec`/`target`, `size` as `/timeline`):
False-color RGBA PNG combining three SPHEREx detectors (`r`=long, `g`=medium, `b`=short
wavelength) using `asinh`-stretched float32 arrays. Returns `404` with `missing_detectors`
when any of the three detector timelines is not ready; never starts a build.

Static export for a demo without internet: `python -m app.export --out <folder>` writes
`targets.json`, `timeline/<slug>_d<detector>_<size>.json` (same body as the API, with
`image_url` relative to the folder) and `images/<id>.png`. Only ready timelines are exported;
the diff images are not.

## Float data for analysis (work in progress)

The PNGs are stretched and 8-bit, so they cannot be used to subtract epochs or measure
fluxes. For the `large` size the build also produces `EpochImage.npz`: a compressed `.npz`
with float32 `image` and `variance` (co-added, no stretch, holes **not** filled; NaN =
no data). Smaller sizes are central crops of it.

Served at `/images/{id}.npz` (`npz_url` in each epoch of the `large` size). Timelines built before the `npz` column existed have no arrays (and `/timeline/diff` answers `404`): delete them to rebuild.

Spectra need one row per exposure (wavelength, flux), not the per-epoch co-add. Not done.

## Tests

```bash
pytest
```

The tests use synthetic FITS files and an in-memory store, so they need neither network nor
database. The `PostgresStore` tests run only when `NEBO_TEST_DATABASE_URL` points to a
throwaway database.

If VS Code reports `Import "fastapi" could not be resolved`, select the interpreter
`backend/.venv` (*Python: Select Interpreter*).
