from fastapi import FastAPI

_API_PREFIX = "/api_v1"


def register_routes(app: FastAPI) -> None:
    from .art_preview import router as art_router
    from .config import router as config_router
    from .library.artists import router as artists_router
    from .library.artwork import router as artwork_router
    from .library.metadata import router as metadata_router
    from .library.stats import router as stats_router
    from .monitor import router as monitor_router

    app.include_router(monitor_router, prefix=_API_PREFIX)
    app.include_router(config_router, prefix=_API_PREFIX)
    app.include_router(art_router, prefix=_API_PREFIX)

    lib_prefix = _API_PREFIX + "/library"
    app.include_router(stats_router, prefix=lib_prefix)
    app.include_router(metadata_router, prefix=lib_prefix)
    app.include_router(artwork_router, prefix=lib_prefix)
    # artists last within library — contains wildcard {artist_name:path} routes
    app.include_router(artists_router, prefix=lib_prefix)
