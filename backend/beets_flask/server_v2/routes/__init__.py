from fastapi import APIRouter, FastAPI

_API_PREFIX = "/api_v1"


def register_routes(app: FastAPI) -> None:
    from .monitor import router as monitor_router

    # Add routers here as each module is migrated from server_v2/routes/<module>.py
    app.include_router(monitor_router, prefix=_API_PREFIX)
