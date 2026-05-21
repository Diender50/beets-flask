import os
from urllib.parse import quote_plus

import aiohttp
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from beets_flask.logger import log
from beets_flask.utility import AUDIO_EXTENSIONS

router = APIRouter(prefix="/art", tags=["art"])


@router.get("")
async def redirect_external_art(request: Request, url: str | None = None):
    if not url:
        raise HTTPException(status_code=400, detail="url query param is required.")

    redirect_url: str | None = None
    if "spotify" in url:
        redirect_url = await get_spotify_art(url)
    elif "musicbrainz" in url:
        redirect_url = await get_musicbrainz_art(url)
    elif url.startswith("file://"):
        return await get_folder_art(request, url)

    if redirect_url:
        return RedirectResponse(url=redirect_url, status_code=302)
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


async def get_musicbrainz_art(url: str) -> str | None:
    release_id = url.split("/")[-1]
    return f"https://coverartarchive.org/release/{release_id}/front-250"


async def get_folder_art(request: Request, url: str) -> RedirectResponse:
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

    # Redirect to the artwork endpoint (mirrors url_for("backend.library.artwork.file_art"))
    filepath = quote_plus(path + "/" + files[0])
    target = str(request.base_url) + f"api_v1/library/file/{filepath}/art"
    return RedirectResponse(url=target, status_code=302)
