"""ETL pipeline: real SPHEREx images from IRSA -> processing -> PostgreSQL.

    python -m app.etl run                                   # whole catalogue, detectors 1-6
    python -m app.etl run --targets wise-0855 --detectors 5,6
    python -m app.etl run --coords "269.4,4.77;133.76,-7.24" --detectors 3
    python -m app.etl run --file fields.csv                 # one "ra,dec" per line
    python -m app.etl run --rebuild                         # redo ready ones (new data/settings)
    python -m app.etl worker                                # build what the API queued

``run`` builds the given fields now (ready timelines are skipped, so it is safe to re-run).
With ``--rebuild`` ready timelines are rebuilt too, with a fresh IRSA query: they keep serving
their old images until the new ones replace them, and keep them if the rebuild fails.
``worker`` is for NEBO_BUILD_MODE=queue: the API only queues new fields and this process builds
them, so the API can run on a platform that throttles CPU between requests.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from . import db
from .service import TimelineService
from .targets import TARGETS


def parse_coords(text: str) -> list[tuple[float, float]]:
    """"ra,dec;ra,dec" or one "ra,dec" per line; # starts a comment. Validates the ranges."""
    coords = []
    for item in text.replace(";", "\n").splitlines():
        item = item.split("#")[0].strip()
        if not item:
            continue
        ra, dec = (float(v) for v in item.split(","))
        if not (0.0 <= ra < 360.0 and -90.0 <= dec <= 90.0):
            raise ValueError(f"Coordinates out of range: ra={ra}, dec={dec}")
        coords.append((ra, dec))
    return coords


def run_batch(
    service: TimelineService,
    targets: list[str],
    coords: list[tuple[float, float]],
    detectors: list[int],
    rebuild: bool = False,
) -> int:
    """Build every (field, detector); returns how many did not end up ready."""
    patches = [service.resolve_patch(target_slug=slug) for slug in targets]
    patches += [service.resolve_patch(ra=ra, dec=dec) for ra, dec in coords]
    failures = 0
    for patch in patches:
        name = patch.target_slug or f"{patch.ra:.4f},{patch.dec:+.4f}"
        for detector in detectors:
            started = time.monotonic()
            try:
                timeline = (service.rebuild_now if rebuild else service.build_now)(patch, detector)
            except Exception as error:  # Rebuild failed; the old images are still served.
                print(f"{name:24} D{detector}: kept old  ({type(error).__name__}: {error})")
                failures += 1
                continue
            status = timeline.status if timeline else "missing"
            note = f" ({timeline.error})" if timeline and timeline.error else ""
            print(f"{name:24} D{detector}: {status:8} {time.monotonic() - started:6.0f}s{note}")
            failures += status != "ready"
    return failures


def run_worker(service: TimelineService, once: bool, poll_s: float, stop: threading.Event) -> None:
    """Build queued timelines until stopped (or, with ``once``, until the queue is empty)."""
    while not stop.is_set():
        if service.work_one():
            continue
        if once:
            return
        stop.wait(poll_s)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.etl", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Build fields now.")
    run.add_argument("--targets", help="Comma-separated catalogue slugs.")
    run.add_argument("--coords", help='"ra,dec;ra,dec" in ICRS degrees.')
    run.add_argument("--file", type=Path, help="Text file with one ra,dec per line.")
    run.add_argument("--detectors", default="1,2,3,4,5,6", help="Comma-separated detectors.")
    run.add_argument(
        "--rebuild", action="store_true", help="Also rebuild ready timelines with fresh data."
    )
    work = commands.add_parser("worker", help="Build the timelines the API queued.")
    work.add_argument("--once", action="store_true", help="Exit when the queue is empty.")
    work.add_argument("--poll", type=float, default=5.0, help="Seconds between empty polls.")
    args = parser.parse_args(argv)

    try:
        store = db.get_store()
    except db.DatabaseNotConfigured as error:
        print(error, file=sys.stderr)
        return 1
    store.upsert_targets(TARGETS)
    service = TimelineService(store)

    if args.command == "worker":
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        run_worker(service, args.once, args.poll, stop)
        return 0

    coords = parse_coords(args.coords) if args.coords else []
    if args.file:
        coords += parse_coords(args.file.read_text())
    targets = args.targets.split(",") if args.targets else []
    if not targets and not coords:
        targets = [t["slug"] for t in TARGETS]
    detectors = [int(d) for d in args.detectors.split(",")]
    return 1 if run_batch(service, targets, coords, detectors, args.rebuild) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
