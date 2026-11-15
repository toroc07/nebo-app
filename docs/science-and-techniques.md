# Science, numbers and techniques

Every physical quantity, constant, threshold, metric and technique Nebo uses, with what it is
for and where it lives. Use it to answer "why this number?" without reading the code.

> **Keep this file true.** If you change a constant, a threshold or a formula listed here,
> update its row in the same PR (checklist in [`AGENTS.md`](../AGENTS.md#keeping-docs-in-sync)).
> References are `file` + symbol, not line numbers, so they survive edits.
> How the pieces connect is in [`architecture.md`](architecture.md); where the data comes from is
> in [`data-sources.md`](data-sources.md); the lab viewer math is in
> [`observation-lab.md`](observation-lab.md#pixel--sky-math).

Contents:
[1. Sky geometry and coordinates](#1-sky-geometry-and-coordinates) ·
[2. SPHEREx bands](#2-spherex-bands) ·
[3. Epochs and proper motion](#3-epochs-and-proper-motion) ·
[4. Imaging and display](#4-imaging-and-display) ·
[5. Photometry](#5-photometry) ·
[6. Change detection and catalogue matching](#6-change-detection-and-catalogue-matching) ·
[7. Science models (simulated)](#7-science-models-simulated) ·
[8. Backend operations](#8-backend-operations) ·
[9. Frontend techniques](#9-frontend-techniques) ·
[10. Known inconsistencies](#10-known-inconsistencies)

**Real vs simulated.** Rows marked *(sim)* come from demo profiles that the API labels as
simulated (`models.SIMULATED_NOTE`). Everything else is computed from real SPHEREx, Gaia DR3 or
CatWISE2020 data. The full split is in [architecture §9](architecture.md#9-real-vs-simulated-data).

---

## 1. Sky geometry and coordinates

| Concept | Value / formula | Where | Why |
| --- | --- | --- | --- |
| Pixel scale | 6.15″ / px (`PIXEL_SCALE_ARCSEC`) | `backend/app/config.py` | SPHEREx native scale; output grid, arcsec conversions, default match radius |
| Patch sizes | small 0.05° (3′), medium 0.1° (6′), large 0.25° (15′) (`SIZES_DEG`) | `config.py` | The three zoom levels of a field |
| Grid side | `n = ceil(size / (6.15/3600))`, forced odd → 31 / 59 / 147 px | `imaging.py` | Odd side so the target is exactly the centre pixel |
| Fetch size | `0.25·√2` ≈ 0.354° | `config.py` | Cutout large enough to rotate north-up with no empty corners |
| Output WCS | TAN projection, `crpix = (n+1)/2`, `cdelt = [-scale, +scale]` | `imaging.py` | North up, east left on every image |
| FITS → PNG | `np.flipud`; `y_png = side − 1 − y` | `imaging.py`, `crossmatch.py`, `main.py` | FITS row 0 is the bottom, PNG row 0 the top |
| Reprojection | Nearest neighbour (`world_to_pixel_values` + `rint`) | `imaging.py` | Put every frame on the same grid without smoothing the noise |
| Sector corners | NW/NE/SE/SW at pixel edges (±0.5 px), ICRS polygon | `imaging.py` | `sector.corners` in the API, footprints on the sky map |
| Angular separation | Haversine: `2·asin(√(sin²(Δδ/2) + cosδ₁cosδ₂ sin²(Δα/2)))` | `store.angular_separation_deg`, `gaia.separation_arcsec`, `frontend/lib/coordinates.ts` `angularDistance` | Stable at small angles (patch reuse, matching) |
| Patch reuse radius | 30″ (`PATCH_MATCH_RADIUS_ARCSEC`) | `config.py`, `service.py` | Nearby searches open the same preloaded patch |
| Fast-mover track | Positions 1990–2027 every 0.5 yr (`TRACK_MJDS`) | `service.py` | Coordinates typed at any epoch still land on the catalogued object |
| "At map centre" | 0.05° (3′) (`AT_MAP_CENTRE_DEG`) | `frontend/lib/coordinates.ts` | The cockpit names the object under the reticle |
| RA normalisation | `((ra % 360) + 360) % 360` | `coordinates.ts` `normalizeRa` | Wrap-around at 0h |
| RA/Dec parts | RA in 0.01 s, Dec in 0.1″; `ra = (h + m/60 + s/3600)·15` | `coordinates.ts` | Sexagesimal coordinate panel and arrow-key steps (h = 15°) |
| Coordinate validation | `0 ≤ ra < 360`, `−90 ≤ dec ≤ 90` | `etl.parse_coords`, `frontend/lib/api.ts`, `frontend/lib/fieldLink.ts` | Reject bad input at every entry point |
| Sidereal time | GMST, Meeus 12.4 | `coordinates.ts` | Earth sub-point under the observed sky position (cockpit globe) |
| All-sky map | Hammer equal-area, centred on RA 12h, east left, closed-form inverse | `coordinates.ts` | Cockpit overview map |
| Lab pixel ↔ sky | Gnomonic (TAN) about the centre pixel `((w−1)/2, (h−1)/2)` | `frontend/lib/lab/sky.ts` | Coordinates under the cursor without a full WCS |

## 2. SPHEREx bands

| Concept | Value | Where | Why |
| --- | --- | --- | --- |
| Detectors | D1 0.75–1.09 · D2 1.10–1.62 · D3 1.63–2.41 · D4 2.42–3.82 · D5 3.83–4.41 · D6 4.42–5.00 µm | `backend/app/irsa.py` | One detector = one band; never mix detectors in a comparison |
| Band name in ADQL | `SPHEREx-D{n}`, error outside 1–6 | `irsa.bandpass_name` | `energy_bandpassname` filter on IRSA |
| Defaults | Detector 3; RGB composite R = D6, G = D3, B = D1; per-target recommendation | `main.py`, `targets.py` | Cold brown dwarfs (WISE 0855) only show in D6 |
| Spectral channels | 102 channels (id, band, λc, λmin, λmax, R) | `science_catalogs.py` | Map each frame to a channel for spectra |
| Channel lookup | Exact `[λmin, λmax]` hit, else nearest λc if `|Δλ| ≤ 0.12 µm` | `science_catalogs.channel_for_wavelength` | Frame wavelength comes from the spectral WCS (`key="W"`) at the target pixel |
| Dead channels | 51, 52 (`BLANK_CHANNELS`) | `science_catalogs.py` | Dichroic gap near 2.4 µm; never imputed as zero |
| Spectrum markers | H₂O 3.05, NH₃ 3.20, CH₄/PAH 3.30, CH₃OH 3.53, Brα 4.05, CO₂ 4.27, CO 4.67 µm | `frontend/components/science/SpectrumChart.tsx` | Visual reference lines on the spectrum |

## 3. Epochs and proper motion

| Concept | Value / formula | Where | Why |
| --- | --- | --- | --- |
| Catalogue epoch | 2026.2 (`REFERENCE_MJD = 51544.5 + 26.2·365.25`) | `backend/app/ephemeris.py` | `targets.py` coordinates are where objects are now |
| Linear propagation | `yrs = (mjd − ref)/365.25`; `δ' = δ + μδ·yrs/3.6e6`; `α' = α + μα*·yrs/3.6e6/cosδ` | `ephemeris.expected_position` | Expected position at each SPHEREx epoch (μα* already includes cosδ) |
| Gaia epoch | J2016.0 (MJD 57388.5) | `gaia.py` | Propagate Gaia stars to each epoch |
| CatWISE epoch | 2015.4 | `wise.py` | Same for CatWISE |
| Gaia distance | `1000 / parallax` (pc), only if parallax > 0.1 mas; 1 pc = 3.26156 ly | `gaia.py`, `frontend/lib/overlays.ts` | Detail card; tiny parallaxes give meaningless distances |
| Epoch split | New epoch if gap > 30 d; spans cut at 14 d; spans < 12 frames merged into a neighbour | `service.group_into_epochs`, `split_into_epochs`, `config.py` | SPHEREx revisits a field in passes ~6 months apart; deep fields are observed for months |
| Frames per epoch | ≤ 16, spread evenly over wavelength (`select_evenly`) | `config.py`, `service.py` | Bounded build time with full band coverage |

## 4. Imaging and display

| Concept | Value / formula | Where | Why |
| --- | --- | --- | --- |
| Zodiacal light | `image = IMAGE − ZODI` | `imaging.py` | Remove the smooth foreground; images in MJy/sr |
| Flags | Science exclusion list (SUR_ERROR … HALO); display drops only NONFUNC, MISSING_DATA | `imaging.py` | Keep bad pixels out of photometry but not out of the picture |
| Co-add | Inverse variance: `mean = Σ(w·x)/Σw`, `var = 1/Σw`, `w = 1/var` | `imaging.py` | One image per epoch; noise falls as 1/√n |
| Hole filling | NaN groups ≤ 16 px not touching the edge → max of their border | `imaging.py` | Display only: saturated star cores would look black |
| Stretch limits | Percentiles 1 and 99.7, **shared by all epochs** of a size | `imaging.stretch_limits`, `main.py` (`display_min/max`) | Same scale for every epoch → visible changes are real |
| Stretch curve | `asinh(clip((x−lo)/(hi−lo))·10) / asinh(10)` | `imaging.to_png` | Shows faint sources and bright stars together |
| Palettes | amber; inferno | `imaging.py` | Colour only; never changes the data |
| Difference image | `B − A`, symmetric limit = p99.7 of `|diff|`, asinh softening 10; red brighter, blue fainter (`X-Diff-Limit` header) | `imaging.py`, `main.py` | Show what changed between two epochs |
| RGB composite | Each band asinh between its own p1 and p99.5; transparent where any band is NaN | `imaging.py` (`/timeline/rgb`) | Colour hints at temperature (cold objects are red) |
| Pixelated upscale | `image-rendering: pixelated` | `lab.module.css`, `science.module.css`, `field.module.css` | A 31 px image enlarged must show its real pixels, not a blur |

## 5. Photometry

| Concept | Value / formula | Where | Why |
| --- | --- | --- | --- |
| Units | MJy/sr → µJy: `× rad(6.15/3600)² × 1e12` | `service.py` | Fluxes users can compare with catalogues |
| Quick-look aperture | 3×3 sum around the target, 3% floor | `service.py` | Per-exposure photometry while building |
| ePSF kernel | 5×5 Gaussian, FWHM 1.22 px, `σ = max(0.35, FWHM/2.35482)` ≈ 0.52 px, sub-pixel offset, sum 1 | `metrics.gaussian_epsf_kernel` | SPHEREx PSF is about one pixel wide |
| Optimal (PSF-weighted) flux | `F = Σ(P·N/V) / Σ(P²/V)`, `σ = √(1/Σ(P²/V))`, `SNR = F/σ`; aperture r = 2 px; background = median of annulus 3–6.5 px | `metrics.py` | Best SNR for a point source; this is the measured `image_photometry` |
| Systematic floor | `σ_rep = hypot(σ_stat, 0.03·|F|)` | `science_catalogs.py` | Calibration is not better than ~3% |
| Saturation | OVERFLOW or SUR_ERROR inside the 5×5 box (`saturated_near`, r = 2) | `imaging.py`, `service.py`, `main.py` | Saturated epochs report flux as a lower limit (≥), no σ/SNR |
| PSF quality | `q_fit`, χ²_psf (dof n−3), `C_PSF`, `C80/20 = 5·log10(r80/r20)`, elongation | `metrics.py` | Features for the event classifier: point source vs artefact |
| Colour indices | NSDI `(FA−FB)/(FA+FB)` with propagated σ; ratios | `science_catalogs.py` | Compare bands with honest errors |
| Spectral indices *(sim)* | 17 indices, significant if SNR ≥ 3; equivalent width `Σ(1 − F/Fcont)·Δλ` | `metrics.py`, `science_catalogs.py` | Molecular absorption (CH₄, H₂O, CO₂) |

## 6. Change detection and catalogue matching

| Concept | Value / formula | Where | Why |
| --- | --- | --- | --- |
| Robust noise | `σ = 1.4826·MAD` (floor 1e-6) | `crossmatch.py` | MAD ignores the sources themselves; 1.4826 makes it equal σ for Gaussian noise |
| Change detection | `B − A` of co-adds minus its median; peaks with `|x|/σ ≥ 4` (API range 2–20), 3×3 local max, ≥ 3 px apart, ≤ 25 candidates (`truncated` past that) | `crossmatch.detect_epoch_changes`, `main.py` (`/candidates`) | Simple difference imaging, no PSF matching (SPHEREx PSF is stable) |
| Known vs new | `catalogued_object` if a Gaia (epoch A or B) or CatWISE (epoch B) source is within 6.15″ (1 px), else `candidate_signal` | `crossmatch.classify_changes` | Separate catalogued objects from uncatalogued movements |
| UI labels | "Catalogued object" / "Candidate signal" / "Cold candidate (no Gaia)"; ≤ 8 labels (all cold candidates + strongest SNR) | `frontend/lib/overlays.ts` | Honest wording: never "Planet X found" |
| Cold candidate (WISE) | No Gaia within 3″ (0.1–30) **and** `W1 − W2 ≥ 1.0` | `main.py` (`/wise`) | Cold brown dwarfs are red in W1−W2 and invisible to Gaia |
| Alignment check | Gaia stars with pm ≤ 20 mas/yr, 7×7 box, peak ≥ 3σ, ≥ 3 stars, median offset; warning if > 0.5 px; rms in ″ = px·6.15 | `crossmatch.py` (`/alignment`) | Prove epochs are registered, so a shift is motion and not a WCS error |
| Target position validation | 7×7 box at the expected pixel, background = median of a 5–10 px annulus; 2D Gaussian fit to finite pixels (flux-weighted centroid as start and fallback); detected if peak S/N ≥ 5; pass if offset ≤ 1 px (6.15″) | `position_report.py` (CLI, `docs/position-validation.md`) | Prove the proper-motion ephemeris puts each target where it really is in every epoch, saturated stars included |
| Simulated offset | dx = 2, dy = −1 px (≈ 12″), labelled | `frontend/lib/overlays.ts` | Demo of what a misalignment would look like |
| Overlay cone | Gaia/CatWISE radius `0.25·√2/2 + 0.05` ≈ 0.227° | `main.py` | One query covers the large patch plus fast movers |
| Catalogue limits | Gaia G < 18, CatWISE W2 < 17.5, ≤ 5000 rows; if capped, `g_complete` = faintest G returned | `gaia.py`, `wise.py`, `main.py` | "No Gaia star" is only true down to that magnitude |
| DB cross-match | 15″, cone 0.05°, ≤ 50 rows | `db.py` (`sync-catalogs`) | Per-target catalogue links |
| Suggestions | Gaia `pm > 500 mas/yr OR parallax > 50 mas`, `G < 14`, r = 30°, plus curated Barnard, Proxima, Kapteyn, Ross 154 | `gaia.py`, `main.py` (`/explore/suggested`) | Nearby, fast stars where change is visible |
| Gaia fast mover (lab) | 100 mas/yr | `frontend/lib/lab/gaia.ts` | Highlight stars that move visibly between epochs |

## 7. Science models (simulated)

These run on demo profiles; real catalogue values (Gaia distance, pm, W1−W2) overwrite the
synthetic ones when available. Shown in `ModelsAndMetricsPanel` as "candidate signal", never as
a discovery.

| Concept | Value / formula | Where |
| --- | --- | --- |
| Difference SNR map | `S = (B−A)/√(VA+VB)`; Z_mono in r ≤ 2.5; dipole `√|Z+·Z−|` if Z+ > 3 and Z− < −3; shift″ = 6.15·distance between poles | `metrics.py` |
| Motion significance | Mahalanobis `D_M = √(Δᵀ Σ⁻¹ Δ)`, significant if ≥ 3; `pm = −Δ·6.15·1000/Δt_yr` mas/yr | `metrics.py` |
| Variability | reduced χ² > 3; von Neumann η; Stetson J; Lomb-Scargle (320 periods) | `metrics.py` |
| Global score `C_global` | `100·S_snr·S_dipole·S_flags·S_psf`, `S_snr = 1/(1+e^(−0.8(snr−4)))`, `S_psf = exp(−(q−1)²/(2·0.35²))`, flag penalties | `metrics.py` |
| Model 1: event classifier | 5 classes, 16 standardised features, hand-set weights; softmax T = 1.15; hard rules for artefacts and airglow; `is_new_candidate = gaia_dist > 5″ and MOVING`; top-5 SHAP drivers | `models.run_model1_event_classifier` |
| Model 2: spectral type | Planck (`hc/k = 14387.77 µm·K`), 6 templates 260–3150 K; fusion `0.85·ML − 1.2·min(χ²_red, 25)` | `models.py` |
| Model 3: forecast | GP Matérn-3/2 (ℓ = 45 d) + quasi-periodic; alert if Z ≥ 3, D² ≥ 9 or ΔlnL < −11.5 (red if Z ≥ 5); vetoed by Model 1 artefacts; 3σ position cone; horizon 180 d (max 730) | `models.py`, `main.py` |
| Panel thresholds | likelihood high ≥ 70%, medium ≥ 40% | `frontend/components/science/ModelsAndMetricsPanel.tsx` |

## 8. Backend operations

| Concept | Value | Where | Why |
| --- | --- | --- | --- |
| `Retry-After` | 2 s while `queued/querying/downloading/first_light`, else 5 s; 30 s when busy or a catalogue is down | `main.retry_after_for` | Poll fast while early previews arrive, slower after |
| Analyze cooldown | 60 s per patch → 429 | `main.py` | Protect the model endpoint |
| Build limits | 6 parallel downloads, 2 concurrent builds, 6 pending | `config.py` | Stay polite with IRSA and inside the server's memory |
| Timeouts | Cutout 180 s; TAP/SIA/Gaia/WISE 10 s connect, 60 s read | `config.py`, `irsa.py`, `gaia.py`, `wise.py` | |
| Retries | Cutout: 4 retries, `min(5·2ⁿ, 60)·U(0.8, 1.2)`, honours Retry-After; TAP 2, SIA 3, hedge to SIA after 20 s | `irsa.py` | Exponential backoff with jitter; hedging cuts slow TAP tails |
| IRSA outage | waits 15 / 30 / 60 s up to 150 s (`NEBO_ARCHIVE_WAIT_S`) | `service.py`, `config.py` | |
| Stale / failed builds | re-claimed after 900 s; failed retried after 60 s | `config.py` | |
| Progressive waves | `first_light` (1 frame) → `preview_ready` (1 per epoch) → `refining` (up to 16) | `service.py` | Something to look at within seconds for new coordinates |
| HTTP caching | PNG/NPZ `max-age=31536000, immutable`; `api_query_cache` never expires | `main.py` | Image ids change when content changes, so caching forever is safe |
| Chat | 280 chars, 24 h retention, 3 s per message | `chat.py` | |

## 9. Frontend techniques

| Concept | Value / formula | Where | Why |
| --- | --- | --- | --- |
| Aladin Lite | Start on Barnard's star, `fov 180`, AIT projection, SPHEREx HiPS cube frame 40 (~1.86 µm, D3) | `frontend/components/Sky.tsx` | Whole-sky view of real SPHEREx data |
| FoV range | 0.1°–180° | `Sky.tsx`, `coordinates.ts` | |
| FoV gauge | Log scale `t = ln(f/0.1)/ln(1800)`, inverse `0.1·1800^t`; arrows ×2 / ÷2 | `coordinates.ts`, `CockpitScreens.tsx` | Equal steps feel equal across 4 orders of magnitude |
| Wheel zoom | `factor = exp(−Δpx·k)`, k = 0.0015 (0.01 with Ctrl/pinch) | `frontend/lib/lab/viewport.ts` | Exponential zoom is smooth at every scale |
| Viewport limits | ≤ 64 screen px per image px; ≥ 25% of the image visible | `viewport.ts` | Never zoom into nothing or lose the field |
| Nested levels | 147/59/31 crops, smallest that covers the view (margin 0.9) | `frontend/lib/lab/fov.ts`, `levels.ts` | Load the sharpest crop for the current zoom |
| Blink comparator | 800 ms default; 400 / 800 / 1500 ms options, saved preference | `Nebo.tsx`, `Field.tsx`, `ObservationLab.tsx` | Classic way astronomers spot moving objects; adjustable for accessibility |
| Timeline polling | `max(1, Retry-After) s`; field gives up after 3 min; after a 502 waits ≥ 60 s | `frontend/lib/api.ts`, `Field.tsx` | Follow the server's pace, never hammer it |
| Warp timing | `MOTION` (fade-in .35, launch .9, tilt .8, min 1.9, max 12, arrive 1.0 s); `REDUCED` for reduced motion | `frontend/lib/warp.ts` | Effect lasts as long as the data takes, with bounds |
| Warp tunnel | Canvas 2D, 560 streaks, perspective `r = focal·radius/z`, near plane 0.035 | `frontend/lib/warp-render.ts` | Cheap enough for any GPU; not a shader |
| Seeded RNG | `mulberry32`, seed 20261114 | `warp-render.ts`, `WarpOverlay.tsx` | Same tunnel on every run |
| Star hologram | GLSL: value noise, 5-octave fBm, limb darkening `mix(.25, 1, μ^limb)`, rim halo | `frontend/components/StarHologram.tsx` | Decorative star model in the detail view |
| Decorative stars | CSS gradients and fixed arrays (Flight: sine hash) | `cockpit.module.css`, `HomeScene.tsx`, `Flight.tsx` | Deterministic (same on server and client) and separate from real detections |
| GSAP | Entrance 0.18 s `power3.out`, camera pan 1.25 s `power2.inOut`; boot `NEBO_BOOT_MS` 3200 ms | `Nebo.tsx`, `NeboBoot.tsx` | One timeline drives camera and interface |
| Reduced motion | `prefers-reduced-motion` skips GSAP turns and entrance; warp uses `REDUCED` | `Nebo.tsx`, `Cockpit.tsx`, `HomeScene.tsx`, `WarpOverlay.tsx` | Accessibility |
| Pixel-ratio caps | Warp `min(dpr, 1.5)`; hologram `[1, 1.5]`; Flight 1 | `WarpOverlay.tsx`, `StarHologram.tsx`, `Flight.tsx` | Keep mobile GPUs cool |

## 10. Known inconsistencies

Found while writing this document (2026-11-15). Also listed in
[architecture §10](architecture.md#10-known-gaps-and-doc-drift).

- `metrics.py`: a comment says the background annulus ends at r = 6 px; the code uses 6.5. Another
  says the position-variance floor is 0.02 px²; the code uses 0.015.
- `frontend/lib/overlays.ts` hard-codes 6.15″ instead of reading the pixel scale from the API.
- `SpectrumChart.tsx` band shading edges differ slightly from the detector ranges in `irsa.py`.
