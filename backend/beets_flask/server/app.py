from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from quart import Quart
from beets.ui import _open_library

from ..config.flask_config import ServerConfig, init_server_config
from ..logger import log

if TYPE_CHECKING:
    from ..config.flask_config import ServerConfig


def create_app(config: str | ServerConfig | None = None) -> Quart:
    config = config or os.getenv("BEETSFLASK_ENV", None)
    # create and configure the app
    app = Quart(__name__, instance_relative_config=True)

    config = init_server_config(config)
    app.config.from_object(config)
    # make routes with and without trailing slahes the same
    app.url_map.strict_slashes = False
    app.json = CustomProvider(app)

    global socketio
    # app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)

    # sqlite
    from ..database import setup_database

    setup_database(app)

    # Register different blueprints & websocket routes
    # In production, we use the frontend.py route to deliver vite's dist folder
    from .routes import register_routes
    from .websocket import register_socketio

    register_routes(app)
    register_socketio(app)

    # Warm once at process startup. This is intentionally synchronous so the app
    # starts in a known cache-ready state even when Quart lifecycle hooks are skipped
    # by ASGI server integration details.
    warm_enabled = os.getenv("BEETSFLASK_WARM_MISSING_ON_START", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if warm_enabled:
        from ..config import get_config
        from .routes.library.artists import ensure_missing_cache_warmed_for_all_artists

        lib = None
        try:
            lib = _open_library(get_config())
            result = ensure_missing_cache_warmed_for_all_artists(lib=lib, force_recompute=False)
            log.info(
                "missing_albums startup warmup total=%s cached_before=%s warmed=%s failed=%s",
                result["artists_total"],
                result["artists_cached_before"],
                result["artists_warmed"],
                result["artists_failed"],
            )
        except Exception as exc:
            log.warning("missing_albums startup warmup failed: %s", exc)
        finally:
            close_func = getattr(lib, "close", None)
            if callable(close_func):
                try:
                    close_func()
                except Exception:
                    pass

    log.debug("Quart app created!")

    return app


# ------------------------------- Json encoder ------------------------------- #
# Allows to serialize bytes and datetime objects in dictionaries to json
# The default encoder does not support this!
# Has to be added to the app with app.json = CustomProvider(app)
# FIXME: We might be able to remove this once our serialized state does not
# contain bytes or datetime objects

from enum import Enum

from quart.json.provider import DefaultJSONProvider


class CustomProvider(DefaultJSONProvider):
    def dumps(self, obj: Any, **kwargs: Any) -> str:
        return json.dumps(obj, cls=Encoder, **kwargs)


class Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bytes):
            # Mainly used for paths
            # b'/path/to/file' -> '/path/to/file'
            # Might yield strange results for other byte objects
            return o.decode("utf-8")

        if isinstance(o, (datetime, date)):
            return o.isoformat()

        # Dataclasses are not serializable by default
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)

        # Enum values are not serializable by default
        if isinstance(o, Enum):
            return o.value

        return json.JSONEncoder.default(self, o)
