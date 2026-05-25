import os
from urllib.parse import quote_plus

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from beets_flask.logger import log
from beets_flask.utility import AUDIO_EXTENSIONS

router = APIRouter(prefix="/art", tags=["art"])

_PROXY_HEADERS = {
    "User-Agent": "beets-flask/1.0 ( https://github.com/pSpitzner/beets-flask )",
    "Accept": "image/webp,image/jpeg,image/png,image/*",
}
_PROXY_TIMEOUT = aiohttp.ClientTimeout(total=10)


async def _proxy_image(url: str) -> Response:
    """Fetch an external image server-side and return its bytes.

    Avoids browser CORS failures that occur when fetch() follows a cross-origin
    redirect to a host (e.g. coverartarchive.org) without CORS headers.
    """
    try:
        async with aiohttp.ClientSession(headers=_PROXY_HEADERS) as session:
            async with session.get(url, timeout=_PROXY_TIMEOUT, allow_redirects=True) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                    return Response(content=data, media_type=ct)
    except Exception as exc:
        log.debug("art proxy failed url=%s: %s", url, exc)
    raise HTTPException(status_code=404, detail="Art not found.")


@router.get("")
async def proxy_external_art(request: Request, url: str | None = None):
    if not url:
        raise HTTPException(status_code=400, detail="url query param is required.")

    target: str | None = None
    if "spotify" in url:
        target = await get_spotify_art(url)
    elif "musicbrainz" in url:
        target = await get_musicbrainz_art(url)
    elif "deezer.com" in url:
        target = await get_deezer_art(url)
    elif url.startswith("file://"):
        return await get_folder_art(request, url)
    elif url.startswith("https://cdn-images.dzcdn.net") or url.startswith("https://e-cdns-images.dzcdn.net"):
        target = url

    if target:
        return await _proxy_image(target)
    raise HTTPException(status_code=404, detail="No art found.")


async def get_spotify_art(url: str) -> str | None:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://embed.spotify.com/oembed?url={quote_plus(url)}"
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("thumbnail_url")
            log.error(f"Error fetching Spotify art: {response.status}")
            return None


async def get_deezer_art(url: str) -> str | None:
    """Resolve Deezer album page URL to cover art CDN URL via Deezer API."""
    import re
    match = re.search(r"deezer\.com/(?:\w+/)?album/(\d+)", url)
    if not match:
        return None
    album_id = match.group(1)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.deezer.com/album/{album_id}", timeout=aiohttp.ClientTimeout(total=8)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("cover_medium") or data.get("cover") or None
        log.error(f"Deezer art fetch failed for album {album_id}")
    except Exception as e:
        log.error(f"Deezer art error: {e}")
    return None


async def get_musicbrainz_art(url: str) -> str | None:
    release_id = url.split("/")[-1]
    return f"https://coverartarchive.org/release/{release_id}/front-250"


async def get_folder_art(request: Request, url: str) -> Response:
    path = url.split("file://")[-1]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Path '{path}' does not exist.")

    files = [
        f
        for f in os.listdir(path)
        if f.endswith(tuple(["." + e for e in AUDIO_EXTENSIONS]))
    ]
    if not files:
        raise HTTPException(status_code=404, detail="No audio files found in folder.")

    filepath = quote_plus(path + "/" + files[0])
    target = str(request.base_url) + f"api_v1/library/file/{filepath}/art"
    # Internal redirect — proxy to avoid CORS on cross-origin targets
    async with aiohttp.ClientSession() as session:
        async with session.get(target, timeout=_PROXY_TIMEOUT) as resp:
            if resp.status == 200:
                data = await resp.read()
                ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                return Response(content=data, media_type=ct)
    raise HTTPException(status_code=404, detail="Folder art not found.")
