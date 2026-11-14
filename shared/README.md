# shared

## demo/

Static export with **synthetic** images, same shape as the API, so the frontend can be built
without a backend or a database.

- `demo/targets.json`: the catalogue (`GET /targets`).
- `demo/timeline/<slug>_d<detector>_<size>.json`: the body of `GET /timeline`
  (5 targets, detectors 3 and 6, sizes small / medium / large). `image_url` is relative to `demo/`.
- `demo/images/<id>.png`: the epoch images (3 epochs per timeline).

The target star moves with its real proper motion (about 1-2 pixels over the 3 epochs) and its
position matches `expected_position`; the other stars are fixed. Brightness and noise are made
up, so do not judge contrast with it. Release is `qr2`, source is fake too.

Not included: `/timeline/diff` images, `.npz` files, `202 building` responses.

Regenerate with `cd backend && python -m tests.demo_export --out ../shared/demo`.
When real data exists, `python -m app.export --out <folder>` writes the same layout.

## demo-color/

Same files and names as `demo/` (same JSON shape, same ids), but the PNGs use the **amber**
palette (black, amber, white) instead of grey. SPHEREx images are single-band infrared, so the
colour is a display palette and not the sky's real colour: say so in the UI. The JSON is
regenerated, so `processed_at` and ids can differ from `demo/`; use one folder or the other.

Regenerate: `cd backend && python -m tests.demo_export --out ../shared/demo-color --palette amber`.
Real data has no such option yet; IRSA's cutout APIs return FITS only, and its viewer offers
colour tables, stretches and 3-colour composites that we would have to reproduce.

## demo-inferno/

Same layout as `demo-color/`, with the **inferno** palette (near-black, purple, orange, pale
yellow): the one IRSA's SPHEREx tutorial uses. Regenerate:
`cd backend && python -m tests.demo_export --out ../shared/demo-inferno --palette inferno`.
