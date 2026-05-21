"""Serve the compiled Vite frontend as a SPA catch-all.

Only enabled in production (FRONTEND_DIST_DIR must exist).
In dev the Vite server (port 5173) proxies /api_v1/* to FastAPI.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def register_frontend(app: FastAPI, dist_dir: str) -> None:
    if not os.path.isdir(dist_dir):
        return
    # Must be mounted AFTER all API routers.
    # Starlette checks routers before mounts, so order in code doesn't strictly matter,
    # but mounting last makes intent explicit.
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
