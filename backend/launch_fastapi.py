"""Launch the FastAPI server on port 5002."""

import os
import sys

import uvicorn

# Ensure the backend directory is on the path regardless of CWD
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from beets_flask.server.app import create_app
from beets_flask.server.websocket import wrap_with_socketio

# app is the socketio-wrapped ASGI app; FastAPI lives inside it.
app = wrap_with_socketio(create_app())

if __name__ == "__main__":
    uvicorn.run(
        "launch_fastapi:app",
        host="0.0.0.0",
        port=5002,
        reload=True,
        reload_dirs=[_backend_dir],
    )
