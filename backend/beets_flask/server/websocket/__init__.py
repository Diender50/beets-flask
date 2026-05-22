"""socketio server + FastAPI wrapper."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import cast

import socketio as _sio_lib
from starlette.types import ASGIApp


class TypedAsyncServer(_sio_lib.AsyncServer):
    def on(self, event: str, namespace: str | None = None) -> Callable: ...  # type: ignore


if os.environ.get("PYTEST_CURRENT_TEST", ""):
    client_manager = None
else:
    client_manager = _sio_lib.AsyncRedisManager("redis://")

sio: TypedAsyncServer = cast(
    TypedAsyncServer,
    _sio_lib.AsyncServer(
        async_mode="asgi",
        logger=False,
        engineio_logger=False,
        cors_allowed_origins="*",
        client_manager=client_manager,
    ),
)


def wrap_with_socketio(fastapi_app: ASGIApp) -> ASGIApp:
    """Wrap FastAPI app with socketio — registers @sio.on handlers via module import."""
    import beets_flask.server.websocket.status as _  # noqa: F401
    import beets_flask.server.websocket.terminal as __  # noqa: F401

    return _sio_lib.ASGIApp(sio, fastapi_app, socketio_path="socket.io")
