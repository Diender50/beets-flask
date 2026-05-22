"""Serve the compiled Vite frontend as a SPA catch-all (production only).

In dev the Vite server (port 5173) proxies /api_v1/* to FastAPI.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Known static asset tokens — serve these directly from disk.
_STATIC_TOKENS = (
    "assets",
    "logo_beets.png",
    "logo_flask.png",
    "favicon.ico",
    "sw.js",
    "manifest.webmanifest",
    "registerSW.js",
    "workbox-",
)


def register_frontend(app: FastAPI, dist_dir: str) -> None:
    """Mount the built Vite frontend with proper SPA fallback.

    Must be called AFTER all API routers so the catch-all doesn't
    shadow /api_v1/* endpoints.
    """
    if not os.path.isdir(dist_dir):
        return

    # Serve /assets/* directly (JS/CSS chunks — high-traffic, cache-friendly).
    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    index = os.path.join(dist_dir, "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(request: Request, full_path: str = "") -> FileResponse:
        """SPA catch-all: serve static files if they exist, index.html otherwise.

        This mirrors the original Quart frontend_bp behaviour so that
        hard refresh (Ctrl+F5) on any client-side route still loads the app.
        """
        if full_path and any(token in full_path for token in _STATIC_TOKENS):
            file_path = os.path.join(dist_dir, full_path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)

        return FileResponse(index)
