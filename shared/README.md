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
