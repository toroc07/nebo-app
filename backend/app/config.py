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
# Set NEBO_DISK_CACHE=0 on Cloud Run: its disk lives in RAM, so a cache that only grows ends in
# an out-of-memory kill (about 4 MB per cutout, ~2000 cutouts for the catalogue). The GCS cache,
# when configured, still avoids downloading a cutout twice.
DISK_CACHE = os.environ.get("NEBO_DISK_CACHE", "1").strip() != "0"

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

# Epochs. SPHEREx revisits most of the sky every ~6 months in passes of 1-2 weeks, so most
# fields only have one epoch per pass. The deep fields near the ecliptic poles (e.g. R Draconis)
# are observed for months on end: a pass longer than EPOCH_MAX_SPAN_DAYS is cut into epochs of
# that length, and an epoch with fewer than MIN_FRAMES_PER_EPOCH frames is folded into its
# neighbour in the same pass, so no epoch is much noisier than the rest. A pass that is short as
# a whole is kept as it is: it is the only image of that date.
# Measured with IRSA in Nov 2026: gap 30 / span 14 / min 12 gives 3-5 epochs for most targets
# and 5-12 for R Draconis; a smaller gap only adds epochs of 1-4 frames.
EPOCH_GAP_DAYS = 30.0
EPOCH_MAX_SPAN_DAYS = 14.0
MIN_FRAMES_PER_EPOCH = 12
# Frames co-added per epoch (noise falls as 1/sqrt(n)); a pass usually has 17-24 per detector.
MAX_FRAMES_PER_EPOCH = 16

# Per-epoch quality warnings shown in the viewer (GET /timeline, epochs[].warnings).
# An epoch co-added from fewer frames than this is at least 2x noisier than a full one (16).
FEW_FRAMES_WARNING = 4
# Fields closer to the galactic plane than this are crowded: at 6.15"/px sources blend together.
DENSE_FIELD_GALACTIC_B_DEG = 10.0

# A "building" timeline not updated for this long is considered dead and is rebuilt.
STALE_BUILD_S = 15 * 60
# A failed timeline can be retried after this long.
FAILED_RETRY_S = 60
# How long a build keeps retrying when IRSA itself is down before it reports the outage.
# Must stay well below STALE_BUILD_S, or a waiting build would be taken for a dead one, and
# below the viewer's 3-minute wait limit so the visitor sees the real cause.
ARCHIVE_WAIT_S = float(os.environ.get("NEBO_ARCHIVE_WAIT_S", "150"))

# Native SPHEREx pixel scale, used for the common output grid.
PIXEL_SCALE_ARCSEC = 6.15

# Local sky background for the per-exposure 3x3 aperture (measured spectrum, P1-1): the clipped
# median of the valid pixels in this annulus around the object, in pixels. The inner radius keeps
# the PSF wings out; on real WISE 0855 cutouts radii 3-7, 4-9 and 5-12 agree within the errors.
LOCAL_BACKGROUND_ANNULUS_PX = (4.0, 9.0)
# Fewer valid annulus pixels than this (edge, masked pixels) gives no background value.
LOCAL_BACKGROUND_MIN_PIXELS = 40

# Progressive wave-by-wave build for coordinate searches (patch.target_slug is None).
PROGRESSIVE_COORDINATE_BUILD = os.environ.get("NEBO_PROGRESSIVE_COORDINATE_BUILD", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
# There is deliberately no switch that makes every coordinate search answer 200 early: the web
# client treats any 200 as final and would stop at the one-frame preview. Clients that can keep
# polling ask for it per request with GET /timeline?wait_for=first_light|preview.

