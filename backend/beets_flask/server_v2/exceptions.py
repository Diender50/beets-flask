from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from beets_flask.server.exceptions import (
    ApiException,
    UserException,
    to_serialized_exception,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(request: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=to_serialized_exception(exc),
        )

    @app.exception_handler(UserException)
    async def _user(request: Request, exc: UserException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=to_serialized_exception(exc),
        )

    @app.exception_handler(Exception)
    async def _generic(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=to_serialized_exception(exc),
        )
