"""Alias of ``python -m app.etl run`` (same flags: --targets, --detectors)."""

import sys

from .etl import main

if __name__ == "__main__":
    sys.exit(main(["run", *sys.argv[1:]]))
