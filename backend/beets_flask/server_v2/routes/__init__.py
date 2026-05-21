from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_API_PREFIX = "/api_v1"


def register_routes(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .art_preview import router as art_router
    from .config import router as config_router
    from .db_models import candidate_router, folder_router, session_router, task_router
    from .discovery import router as discovery_router
    from .inbox import router as inbox_router
    from .library.artists import router as artists_router
    from .library.artwork import router as artwork_router
    from .library.audio import router as audio_router
    from .library.metadata import router as metadata_router
    from .library.resources import router as resources_router
    from .library.stats import router as stats_router
    from .monitor import router as monitor_router

    app.include_router(monitor_router, prefix=_API_PREFIX)
    app.include_router(config_router, prefix=_API_PREFIX)
    app.include_router(art_router, prefix=_API_PREFIX)
    app.include_router(inbox_router, prefix=_API_PREFIX)
    app.include_router(discovery_router, prefix=_API_PREFIX)

    # DB model state CRUD
    app.include_router(session_router, prefix=_API_PREFIX)
    app.include_router(folder_router, prefix=_API_PREFIX)
    app.include_router(task_router, prefix=_API_PREFIX)
    app.include_router(candidate_router, prefix=_API_PREFIX)

    lib_prefix = _API_PREFIX + "/library"
    app.include_router(stats_router, prefix=lib_prefix)
    app.include_router(metadata_router, prefix=lib_prefix)
    app.include_router(artwork_router, prefix=lib_prefix)
    app.include_router(audio_router, prefix=lib_prefix)
    # resources before artists — both have {id:path} style routes
    app.include_router(resources_router, prefix=lib_prefix)
    # artists last — wildcard {artist_name:path} routes must be registered after specifics
    app.include_router(artists_router, prefix=lib_prefix)
