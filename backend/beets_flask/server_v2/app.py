from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from beets_flask.logger import log

from .exceptions import register_exception_handlers
from .json_encoder import CustomJSONResponse


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import beets_flask.database.setup as _db
    from beets_flask.config.flask_config import init_server_config

    init_server_config(os.getenv("BEETSFLASK_ENV", None))
    _db.setup_database()

    warm_enabled = os.getenv("BEETSFLASK_WARM_MISSING_ON_START", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if warm_enabled:
        from beets.ui import _open_library

        from beets_flask.config import get_config
        from beets_flask.server.routes.library.artists import (
            ensure_missing_cache_warmed_for_all_artists,
        )

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
            if lib and callable(getattr(lib, "close", None)):
                try:
                    lib.close()
                except Exception:
                    pass

    yield

    if hasattr(_db, "session_factory"):
        _db.session_factory.remove()
    log.debug("FastAPI app shutdown.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Beets-Flask API",
        version="2.0.0",
        lifespan=_lifespan,
        default_response_class=CustomJSONResponse,
    )

    register_exception_handlers(app)

    from .routes import register_routes

    register_routes(app)

    log.debug("FastAPI app created.")
    return app
