"""Write ready timelines to static files, for a demo without internet or a database.

    python -m app.export --out ../frontend/public/demo
    python -m app.export --out demo --targets wise-0855 --detectors 5,6 --sizes medium

Layout (``image_url`` is relative to the output folder; everything else is the API payload):
    targets.json
    timeline/<slug>_d<detector>_<size>.json   same body as GET /timeline
    images/<id>.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import config, db
from .main import timeline_payload
from .service import TimelineView
from .store import Store


def export(store: Store, out: Path, slugs: list[str], detectors: list[int], sizes: list[str]) -> int:
    """Export what is ready; returns how many timelines were skipped."""
    (out / "timeline").mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    (out / "targets.json").write_text(json.dumps(store.list_targets(), indent=2))
    skipped = 0
    for slug in slugs:
        patch = store.find_patch_for_target(slug)
        for detector in detectors:
            timeline = store.get_timeline(patch.id, detector) if patch else None
            if timeline is None or timeline.status != "ready":
                print(f"skip {slug} D{detector}: not ready", file=sys.stderr)
                skipped += 1
                continue
            for size in sizes:
                view = TimelineView("ready", patch, detector, timeline, store.list_images(timeline.id, size))
                payload = timeline_payload(view, size, store)
                for image, epoch in zip(view.images, payload["epochs"], strict=True):
                    (out / "images" / f"{image.id}.png").write_bytes(store.get_png(image.id) or b"")
                    epoch["image_url"] = f"images/{image.id}.png"
                    epoch.pop("npz_url", None)
                name = f"{slug}_d{detector}_{size}.json"
                (out / "timeline" / name).write_text(json.dumps(payload, indent=2))
    return skipped


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.export", description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--targets", help="Comma-separated slugs (default: the whole catalogue).")
    parser.add_argument("--detectors", default="1,2,3,4,5,6")
    parser.add_argument("--sizes", default=",".join(config.SIZES_DEG))
    args = parser.parse_args(argv)
    try:
        store = db.get_store()
    except db.DatabaseNotConfigured as error:
        print(error, file=sys.stderr)
        return 1
    slugs = args.targets.split(",") if args.targets else [t["slug"] for t in store.list_targets()]
    skipped = export(
        store, args.out, slugs, [int(d) for d in args.detectors.split(",")], args.sizes.split(",")
    )
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
