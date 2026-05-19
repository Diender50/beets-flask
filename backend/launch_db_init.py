import os

# dirty workaround, we pretend this is a rq worker so we get the logger to create
# a child log with pid
os.environ.setdefault("RQ_JOB_ID", "dbin")

from beets.ui import _open_library

from beets_flask.config.beets_config import get_config
from beets_flask.database import setup_database
from beets_flask.logger import log
from beets_flask.server.routes.library.artists import (
    ensure_missing_cache_warmed_for_all_artists,
)

if __name__ == "__main__":
    log.debug("Launching database init worker")

    # ensue beets own db is created
    config = get_config()
    lib = _open_library(config)

    # ensure beets-flask db is created
    setup_database()

    # Warm missing-albums cache for all artists once at container startup.
    # Only uncached artists are computed, so restarts are fast once populated.
    result = ensure_missing_cache_warmed_for_all_artists(lib=lib, force_recompute=False)
    log.info(
        "missing_albums init warmup total=%s cached_before=%s warmed=%s failed=%s",
        result["artists_total"],
        result["artists_cached_before"],
        result["artists_warmed"],
        result["artists_failed"],
    )

    close_func = getattr(lib, "close", None)
    if callable(close_func):
        close_func()
