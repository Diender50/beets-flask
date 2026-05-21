"""Wrap FastAPI with the existing socketio server.

The sio instance (with AsyncRedisManager) is defined in server/websocket/__init__.py.
Both the Quart server and this FastAPI server share the same sio via Redis pub/sub,
so events emitted by either server reach all connected clients.

NOTE: send_status_update() in server/websocket/status.py currently hardcodes
ws://127.0.0.1:5001 (Quart). This works during the parallel-server phase.
Update that URL to :5002 once Quart is removed.
"""

from __future__ import annotations

import socketio as _sio_lib
from starlette.types import ASGIApp


def wrap_with_socketio(fastapi_app: ASGIApp) -> ASGIApp:
    """Return an ASGI app that handles /socket.io and delegates the rest to fastapi_app."""
    from beets_flask.server.websocket import sio
    # Import to trigger @sio.on decorator registration at module level.
    import beets_flask.server.websocket.status as _  # noqa: F401
    import beets_flask.server.websocket.terminal as __  # noqa: F401

    return _sio_lib.ASGIApp(sio, fastapi_app, socketio_path="socket.io")
