# External data sources

Every external service Nebo reads, what it asks for and where in the code. How these pieces fit
together is in [`architecture.md`](architecture.md); the numbers derived from them (bands, pixel
scale, epochs, catalogue limits and match radii) are in
[`science-and-techniques.md`](science-and-techniques.md).

> **Keep this file true.** Adding, removing or changing a source (URL, table, collection,
> release, query, cache or limit) means updating this file, the diagram in
> [`architecture.md` §1](architecture.md#1-system-context) and the
> [changelog](architecture.md#architecture-changelog). See
> [`AGENTS.md`](../AGENTS.md#keeping-docs-in-sync).

## Sources in use

| Source | Endpoint | What we ask | Where in the code | Cached in | Limits and failure modes |
| --- | --- | --- | --- | --- | --- |
| **NASA/IPAC IRSA — TAP** | `https://irsa.ipac.caltech.edu/TAP/sync` (POST, ADQL, VOTable) | SPHEREx Level 2 spectral images covering a point for one detector: `spherex.artifact` JOIN `spherex.plane`, `CONTAINS(POINT, p.poly)`, `energy_bandpassname = 'SPHEREx-D{n}'`, ordered by time | `backend/app/irsa.py` (`build_frames_query`, `_query_frames_tap`, `TAP_SYNC_URL`) | `api_query_cache` (`irsa_spherex_tap`), no expiry | 60 s read timeout, 2 attempts. Often slow or down under load: after 20 s (`TAP_HEDGE_S`) SIA is asked in parallel |
| **NASA/IPAC IRSA — SIA** | `https://irsa.ipac.caltech.edu/SIA` (GET) | Same image list via `POS=CIRCLE ra dec 0.0001`, collections `spherex_dr1`, `spherex_qr3`, `spherex_dr1_deep`, `spherex_qr3_deep`, `dataproduct_subtype = science` | `backend/app/irsa.py` (`_query_frames_sia`, `SIA_COLLECTIONS`) | same as TAP | Lags TAP by about a day; used as hedge and fallback. 3 attempts |
| **NASA/IPAC IRSA — IBE cutouts** | `https://irsa.ipac.caltech.edu/ibe/data/spherex/...?center=ra,decd&size=deg` | A 0.354° cutout of each Level 2 image: multi-extension FITS with IMAGE, VARIANCE, FLAGS, ZODI and the spectral WCS `W` | `backend/app/irsa.py` (`cutout_url`, `fetch_cutout`); read by `backend/app/imaging.py` (`read_cutout`) | Disk (`NEBO_CACHE_DIR`) and optional GCS; processed PNG/NPZ in `timeline_images` | ~4 MB each. Retries 429/5xx with backoff that honours `Retry-After`; 6 downloads in flight per process (IRSA is shared by every team) |
| **NASA/IPAC IRSA — SPHEREx HiPS** | `https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube` | All-sky background map (cube, slice 40) streamed by Aladin Lite in the browser | `frontend/components/Sky.tsx` (`SPHEREX_HIPS`) | Browser cache | Visual reference only; never used for measurements |
| **ESA Gaia DR3** | `https://gea.esac.esa.int/tap-server/tap/sync` (ADQL, CSV) | `gaiadr3.gaia_source`: `source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag, bp_rp`, cone around the patch, `phot_g_mean_mag < g_max`, `TOP 5000`; also nearby/fast stars for `/explore/suggested` | `backend/app/gaia.py` (`build_cone_query`, `query_cone`, `query_suggested_destinations`); served by `/patches/{id}/gaia`, `/explore/suggested`, and cross-matched in `crossmatch.py` | `api_query_cache` (`gaia_dr3_tap`, `gaia_suggested_tap`) | 502 `gaia_unavailable` + `Retry-After: 30` when ESA fails (curated fallback on `/explore/suggested`). Positions propagated from J2016.0 to each epoch |
| **NASA/IPAC IRSA — CatWISE2020** | `https://irsa.ipac.caltech.edu/TAP/sync` (POST, ADQL, CSV) | `catwise_2020`: `source_id, ra, dec, pmra, pmdec, w1mpro, w2mpro, w1sigmpro, w2sigmpro`, cone around the patch, `w2mpro < w2_max`, `TOP 5000` | `backend/app/wise.py` (`build_cone_query`, `query_cone`); served by `GET /patches/{id}/wise` and cross-matched in `crossmatch.py` / `models.py` | `api_query_cache` (`catwise2020_tap`) | 502 `wise_unavailable` + `Retry-After: 30` when IRSA fails. Positions propagated from 2015.4 to each epoch |

### What the SPHEREx data looks like to us

- **Detectors** D1–D6 are different wavelength bands (`irsa.DETECTOR_WAVELENGTH_RANGE_UM`):
  D1 0.75–1.09 µm, D2 1.10–1.62, D3 1.63–2.41, D4 2.42–3.82, D5 3.83–4.41, D6 4.42–5.00.
  Never compare images from different detectors. Cold brown dwarfs like WISE 0855 show up only in D6.
- **Releases** (`dr1`, `qr3`, ...) come from the 4th segment of the image URI
  (`FrameRecord.release`) and are shown per epoch through `epochs[].releases`. Never hard-code them.
- **Epochs**: SPHEREx revisits most of the sky about every 6 months. Frames are grouped into
  epochs by gaps over 30 days (passes longer than 14 days are split), and up to 16 frames per
  epoch are co-added.
- **Pixel scale** 6.15″. Images are reprojected north up, east left.

## Challenge resources and how we use them

Resources listed by the NASA Space Apps 2026 challenge "Planet X and SPHEREx":

| Resource | Used? | How |
| --- | --- | --- |
| [NASA/IPAC IRSA: SPHEREx](https://irsa.ipac.caltech.edu/Missions/spherex.html) | ✅ Core | TAP, SIA, IBE cutouts and HiPS above |
| [IRSA tutorial notebooks](https://caltech-ipac.github.io/irsa-tutorials/) | 📖 Reference | How to access SPHEREx data from Python (TAP, cutouts) |
| [WiseView](http://byw.tools/wiseview) | 💡 Inspiration | The epoch blink comparator follows WiseView's model |
| [Gaia DR3](https://www.cosmos.esa.int/web/gaia/dr3) | ✅ Used | Catalogued stars overlay, to separate known objects from uncatalogued movements |
| [CSA NEOSSat](https://www.asc-csa.gc.ca/eng/satellites/neossat/) and dataset | ❌ Not used | — |
| [Canadian Astronomy Data Centre (CADC)](https://www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/) | ❌ Not used | — |

## Referenced but not queried

- **SIMBAD**: only the source of the hard-coded target coordinates in `backend/app/targets.py` (used as fallback for ultra-cool dwarfs invisible in Gaia DR3).
- `astroquery` is in `requirements.txt` but not imported: plain `requests` calls with explicit
  timeouts are used instead (astroquery/pyvo set no time limit).

## Adding a source

1. Put the client in its own module in `backend/app/` (like `gaia.py`): explicit timeouts,
   retries for transient errors, no secrets in code.
2. Cache responses in `api_query_cache` with a distinct `provider` name.
3. Expose it through the API; the browser should not call third-party science services directly.
4. Add a row to the table above, update the context diagram in `architecture.md` and add a
   changelog line.
5. Respect the source's data-use terms; NASA does not endorse non-U.S. Government sites.
