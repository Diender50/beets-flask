from __future__ import annotations

import json as _stdlib_json
from collections.abc import Awaitable, Callable
from dataclasses import asdict as _asdict
from enum import Enum as _Enum
from dataclasses import dataclass
from functools import wraps
from typing import Concatenate, Literal, ParamSpec, TypeVar

import socketio

from beets_flask.database import db_session_factory
from beets_flask.database.models.states import FolderInDb
from beets_flask.disk import clear_cache
from beets_flask.importer.progress import FolderStatus
from beets_flask.invoker.job import JobMeta
from beets_flask.logger import log
from beets_flask.server.exceptions import (
    InvalidUsageException,
    SerializedException,
    to_serialized_exception,
)

from . import sio
from .errors import sio_catch_exception


@dataclass
class JobStatusUpdate:
    message: str
    num_jobs: int
    job_metas: list[JobMeta]
    exc: SerializedException | None = None
    event: Literal["job_status_update"] = "job_status_update"


@dataclass
class FolderStatusUpdate:
    path: str
    hash: str
    status: FolderStatus
    exc: SerializedException | None = None
    event: Literal["folder_status_update"] = "folder_status_update"


@dataclass
class FileSystemUpdate:
    exc: SerializedException | None = None
    event: Literal["file_system_update"] = "file_system_update"


namespace = "/status"


@sio.on("connect", namespace=namespace)
@sio_catch_exception
async def connect(sid, *args):
    log.debug(f"StatusSocket sid {sid} connected")


@sio.on("folder_status_update", namespace=namespace)
@sio_catch_exception
async def folder_update(sid, data):
    log.debug(f"folder_status_update: {data}")
    await sio.emit("folder_status_update", data, namespace=namespace)


@sio.on("job_status_update", namespace=namespace)
@sio_catch_exception
async def job_update(sid, data):
    log.debug(f"job_status_update: {data}")
    await sio.emit("job_status_update", data, namespace=namespace)


@sio.on("file_system_update", namespace=namespace)
@sio_catch_exception
async def fs_update(sid, data):
    log.debug(f"file_system_update: {data}")
    clear_cache()
    await sio.emit("file_system_update", data, namespace=namespace)


@sio.on("*", namespace=namespace)
@sio_catch_exception
async def any_event(event, sid, data):
    log.debug(f"StatusSocket sid {sid} unhandled event {event} with data {data}")


class _Encoder(_stdlib_json.JSONEncoder):
    def default(self, o):
        from dataclasses import is_dataclass, asdict
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        if isinstance(o, _Enum):
            return o.value
        return super().default(o)


class _JsonModule:
    dumps = staticmethod(lambda obj, **kw: _stdlib_json.dumps(obj, cls=_Encoder, **kw))
    loads = staticmethod(_stdlib_json.loads)


async def send_status_update(
    status: FolderStatusUpdate | JobStatusUpdate | FileSystemUpdate,
):
    client = socketio.AsyncClient(json=_JsonModule)
    await client.connect("ws://127.0.0.1:5002", namespaces=[namespace])
    await client.call(status.event, status, namespace=namespace, timeout=5)
    await client.disconnect()


async def trigger_clear_cache():
    clear_cache()
    await send_status_update(FileSystemUpdate())


R = TypeVar("R")
P = ParamSpec("P")


def emit_folder_status(
    before: FolderStatus | None = None, after: FolderStatus | None = None
) -> Callable[
    [Callable[Concatenate[str, str, P], Awaitable[R]]],
    Callable[Concatenate[str, str | None, P], Awaitable[R]],
]:
    def decorator(
        f: Callable[Concatenate[str, str, P], Awaitable[R]],
    ) -> Callable[Concatenate[str, str | None, P], Awaitable[R]]:
        @wraps(f)
        async def wrapper(hash: str, path: str | None, *args, **kwargs) -> R:
            if path is None:
                with db_session_factory() as db_session:
                    f_on_disk = FolderInDb.get_by(FolderInDb.id == hash, session=db_session)
                    if f_on_disk is None:
                        raise InvalidUsageException("If only hash is given, it must be in the db.")
                    path = f_on_disk.full_path

            if before is not None:
                await send_status_update(FolderStatusUpdate(hash=hash, path=path, status=before))

            try:
                ret = await f(hash, path, *args, **kwargs)
            except Exception as e:
                await send_status_update(
                    FolderStatusUpdate(hash=hash, path=path, status=FolderStatus.FAILED, exc=to_serialized_exception(e))
                )
                raise e

            if after is not None:
                await send_status_update(FolderStatusUpdate(hash=hash, path=path, status=after))

            return ret

        return wrapper

    return decorator
