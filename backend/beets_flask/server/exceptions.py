from __future__ import annotations

import traceback
from typing import NotRequired, TypedDict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class SerializedException(TypedDict):
    type: str
    message: str
    description: NotRequired[str | None]
    trace: NotRequired[str | None]


class ApiException(Exception):
    persist_in_db: bool
    status_code: int = 500

    def __init__(self, *args, status_code: int | None = None, persist_in_db: bool = True):
        super().__init__(*args)
        if status_code is not None:
            self.status_code = status_code
        self.persist_in_db = persist_in_db


class InvalidUsageException(ApiException):
    status_code: int = 400


class NotFoundException(ApiException):
    status_code: int = 404


class IntegrityException(ApiException):
    status_code: int = 409


class NotImportedException(ApiException):
    status_code: int = 409


class UnauthorizedException(ApiException):
    status_code: int = 401


class ForbiddenException(ApiException):
    status_code: int = 403


class NoCandidatesFoundException(ApiException):
    status_code: int = 409

    def __init__(self, *args, status_code: int | None = None, persist_in_db: bool = True):
        if not args:
            try:
                from beets.metadata_plugins import find_metadata_source_plugins
                meta_plugins = [p.data_source for p in find_metadata_source_plugins()]
                msg = (
                    f"Lookup found no candidates. Used '{', '.join(meta_plugins)}'."
                    if meta_plugins else "Lookup found no candidates. No source plugins enabled."
                )
            except Exception:
                msg = "Lookup found no candidates."
            args = (msg,)
        super().__init__(*args, status_code=status_code, persist_in_db=persist_in_db)


class UserException(Exception):
    status_code: int = 422

    def __init__(self, *args, status_code: int | None = None):
        super().__init__(*args)
        if status_code is not None:
            self.status_code = status_code


class DuplicateException(UserException):
    status_code: int = 422


def to_serialized_exception(exception: Exception) -> SerializedException:
    if exception is None:
        return None
    tb: str | None = None
    if exception.__traceback__ is not None:
        tb = "".join(traceback.format_tb(exception.__traceback__))
    return SerializedException(
        type=exception.__class__.__name__,
        message=str(exception),
        description=exception.__doc__,
        trace=tb,
    )


def exception_as_return_value(f):
    from functools import wraps

    @wraps(f)
    async def wrapper(*args, **kwargs):
        try:
            return await f(*args, **kwargs)
        except ApiException as e:
            from beets_flask.logger import log
            log.info(e)
            return to_serialized_exception(e)
        except Exception as e:
            from beets_flask.logger import log
            log.exception(e)
            return to_serialized_exception(e)

    return wrapper


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(request: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=to_serialized_exception(exc))

    @app.exception_handler(UserException)
    async def _user(request: Request, exc: UserException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=to_serialized_exception(exc))

    @app.exception_handler(Exception)
    async def _generic(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content=to_serialized_exception(exc))
