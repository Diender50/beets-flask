"""Periodic new-album notification worker.

Checks every INTERVAL_HOURS hours whether tracked artists have released
new albums (via MusicBrainz + Deezer) and stores notifications in SQLite.

Run alongside the other workers:
    python launch_notification_worker.py
"""

import os
import sys
import time

_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

INTERVAL_HOURS: float = float(os.getenv("NOTIFICATION_INTERVAL_HOURS", "6"))

from beets_flask.config.flask_config import init_server_config
from beets_flask.database.setup import setup_database
from beets_flask.logger import log
from beets_flask.notifications import check_all_followed_artists

init_server_config(os.getenv("BEETSFLASK_ENV", None))
setup_database()

log.info("notification_worker: started interval_hours=%.1f", INTERVAL_HOURS)

while True:
    try:
        total = check_all_followed_artists()
        log.info("notification_worker: cycle done new_notifications=%d", total)
    except Exception as exc:
        log.error("notification_worker: cycle error %s", exc)
    time.sleep(INTERVAL_HOURS * 3600)
