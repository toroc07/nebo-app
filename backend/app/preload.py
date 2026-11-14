"""Seed the catalogue and build its timelines ahead of time, so the demo opens instantly.

    python -m app.preload                       # every target, detectors 1-6
    python -m app.preload --targets wise-0855 --detectors 5,6

Safe to re-run: ready timelines are skipped.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import db
from .service import TimelineService
from .targets import TARGETS


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.preload", description=__doc__)
    parser.add_argument(
        "--targets", help="Comma-separated target slugs (default: the whole catalogue)."
    )
    parser.add_argument("--detectors", default="1,2,3,4,5,6", help="Comma-separated detectors.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        store = db.get_store()
    except db.DatabaseNotConfigured as error:
        print(error, file=sys.stderr)
        return 1

    store.upsert_targets(TARGETS)
    slugs = args.targets.split(",") if args.targets else [t["slug"] for t in TARGETS]
    detectors = [int(d) for d in args.detectors.split(",")]
    service = TimelineService(store)

    failures = 0
    for slug in slugs:
        patch = service.resolve_patch(target_slug=slug)
        for detector in detectors:
            started = time.monotonic()
            timeline = service.build_now(patch, detector)
            status = timeline.status if timeline else "missing"
            note = f" ({timeline.error})" if timeline and timeline.error else ""
            print(f"{slug:16} D{detector}: {status:8} {time.monotonic() - started:6.0f}s{note}")
            failures += status != "ready"
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
