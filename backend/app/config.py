"""Runtime settings, read from environment variables and the backend/.env file."""

import math
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

IRSA_BASE_URL = "https://irsa.ipac.caltech.edu"

# Empty until the shared PostgreSQL database exists; the API then answers 503.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# On-disk cache of downloaded FITS cutouts (not the processed images, those live in Postgres).
CACHE_DIR = Path(os.environ.get("NEBO_CACHE_DIR", BACKEND_DIR / ".cache"))

# Comma-separated list of allowed origins for the frontend. "*" is fine while the API is
# public, read-only and does not use cookies.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("NEBO_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]

# IRSA is shared by every hackathon team: keep the number of parallel downloads modest.
MAX_PARALLEL_DOWNLOADS = int(os.environ.get("NEBO_MAX_PARALLEL_DOWNLOADS", "6"))
MAX_CONCURRENT_BUILDS = int(os.environ.get("NEBO_MAX_CONCURRENT_BUILDS", "2"))
# Builds waiting or running in this process; beyond this, new patches get "busy, retry later".
# Keeps queued builds well below STALE_BUILD_S so they are never mistaken for dead ones.
MAX_PENDING_BUILDS = int(os.environ.get("NEBO_MAX_PENDING_BUILDS", "6"))
# "inline": the API builds missing timelines in its own threads. "queue": the API only queues
# them and a separate `python -m app.etl worker` builds them (needed on Cloud Run, where CPU is
# throttled once the response is sent).
BUILD_MODE = os.environ.get("NEBO_BUILD_MODE", "inline").strip().lower()
HTTP_TIMEOUT_S = float(os.environ.get("NEBO_HTTP_TIMEOUT_S", "180"))

# Display sizes: side of the square patch, in degrees (3, 6 and 15 arcmin).
SIZES_DEG = {"small": 0.05, "medium": 0.1, "large": 0.25}
DEFAULT_SIZE = "medium"
# Cutouts are downloaded once, large enough that the north-up "large" grid has no empty
# corners whatever the rotation of the SPHEREx image (side x sqrt(2)).
FETCH_SIZE_DEG = round(SIZES_DEG["large"] * math.sqrt(2), 4)

# A request this close to an existing patch centre reuses that patch.
PATCH_MATCH_RADIUS_ARCSEC = 30.0

# SPHEREx revisits the whole sky every ~6 months; frames closer than this belong to one epoch.
EPOCH_GAP_DAYS = 30.0
MAX_FRAMES_PER_EPOCH = 8

# A "building" timeline not updated for this long is considered dead and is rebuilt.
STALE_BUILD_S = 15 * 60
# A failed timeline can be retried after this long.
FAILED_RETRY_S = 60

# Native SPHEREx pixel scale, used for the common output grid.
PIXEL_SCALE_ARCSEC = 6.15
