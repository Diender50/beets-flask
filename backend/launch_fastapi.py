"""Launch the FastAPI server on port 5002 (parallel to Quart on 5001)."""

import os
import sys

import uvicorn

# Ensure the backend directory is on the path regardless of CWD
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from beets_flask.server_v2.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "launch_fastapi:app",
        host="0.0.0.0",
        port=5002,
        reload=True,
        reload_dirs=[_backend_dir],
    )
