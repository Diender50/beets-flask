"""Discovery routes: followed artists + album acquisition stubs."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

import aiohttp
from quart import Blueprint, jsonify, request

from beets_flask.config import get_config
from beets_flask.discovery.download import (
    create_download_job,
    delete_download_job,
    get_all_download_jobs,
    get_download_job,
    run_download,
)
from beets_flask.discovery.followed_artists import (
    follow_artist,
    get_followed_artists,
    is_followed,
    unfollow_artist,
)
from beets_flask.logger import log

discovery_bp = Blueprint("discovery", __name__, url_prefix="/discovery")


@discovery_bp.after_request
async def add_cors_headers(response):
    """Add CORS headers to all discovery endpoints."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@discovery_bp.route("/<path:path>", methods=["OPTIONS"])
async def handle_options(path: str):
    """Handle CORS preflight requests."""
    return "", 200


@discovery_bp.route("", methods=["OPTIONS"])
async def handle_root_options():
    """Handle CORS preflight requests for root."""
    return "", 200


def _get_download_path() -> str:
    """Return the first configured inbox path, defaulting to /music/inbox_preview."""
    try:
        config = get_config()
        folders = config["gui"]["inbox"]["folders"].get({})
        if folders:
            for folder_cfg in folders.values():
                path = folder_cfg.get("path", {})
                if isinstance(path, str) and path:
                    return path
                if hasattr(path, "get"):
                    val = path.get("")
                    if val:
                        return str(val)
    except Exception as exc:
        log.warning("Could not read inbox path from config: %s", exc)
    return "/music/inbox_preview"


# ─────────────────────────── Followed Artists ────────────────────────────── #


@discovery_bp.route("/search/artists", methods=["GET"])
async def search_artists():
    """Search MusicBrainz for artists.

    Query param: q (artist name)
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q is required"}), 400

    url = f"https://musicbrainz.org/ws/2/artist?query={quote(q)}&limit=15&fmt=json"
    headers = {"User-Agent": "beets-flask/1.0 ( https://github.com/pSpitzner/beets-flask )"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:
        log.warning("MusicBrainz artist search failed: %s", exc)
        return jsonify({"error": "MusicBrainz search failed"}), 502

    artists = [
        {
            "id": a.get("id"),
            "name": a.get("name", ""),
            "sort_name": a.get("sort-name", ""),
            "disambiguation": a.get("disambiguation", ""),
            "country": a.get("country", ""),
            "score": a.get("score", 0),
            "followed": bool(is_followed(a.get("name", ""))),
        }
        for a in data.get("artists", [])
    ]
    return jsonify(artists)


@discovery_bp.route("/artists", methods=["GET"])
async def list_followed_artists():
    """Return all followed (tracked) artists."""
    return jsonify(get_followed_artists())


@discovery_bp.route("/artists", methods=["POST"])
async def add_followed_artist():
    """Follow an artist by name.

    Body: { name: str }
    """
    data = await request.get_json()
    if not data or not str(data.get("name", "")).strip():
        return jsonify({"error": "name is required"}), 400
    name = str(data["name"]).strip()
    meta = follow_artist(name)
    return jsonify(meta), 201


@discovery_bp.route("/artists/<path:name>", methods=["DELETE"])
async def remove_followed_artist(name: str):
    """Unfollow an artist."""
    unfollow_artist(name)
    return jsonify({"ok": True})


@discovery_bp.route("/artists/<path:name>/status", methods=["GET"])
async def followed_artist_status(name: str):
    """Return whether an artist is followed."""
    return jsonify({"name": name, "followed": is_followed(name)})


@discovery_bp.route("/download", methods=["POST"])
async def start_download():
    """Queue a Deezer album download via deemix (Phase 3).

    Body: { deezer_id: str, album: str, artist: str }
    """
    data = await request.get_json()
    if not data or "deezer_id" not in data:
        return jsonify({"error": "deezer_id is required"}), 400

    deezer_id = str(data["deezer_id"])
    album = str(data.get("album", ""))
    artist = str(data.get("artist", ""))

    job = create_download_job(deezer_id, album, artist)
    output_path = _get_download_path()

    asyncio.ensure_future(run_download(job["job_id"], deezer_id, output_path))

    return jsonify(job), 202


@discovery_bp.route("/downloads", methods=["GET"])
async def list_downloads():
    """Return all download jobs."""
    return jsonify(get_all_download_jobs())


@discovery_bp.route("/downloads/<job_id>", methods=["GET"])
async def get_download(job_id: str):
    """Return a specific download job."""
    job = get_download_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@discovery_bp.route("/downloads/<job_id>", methods=["DELETE"])
async def remove_download(job_id: str):
    """Remove a download job record."""
    delete_download_job(job_id)
    return jsonify({"ok": True})

