"""Artist routes — business logic reused from server/routes/library/artists.py."""

import json
import urllib.request
from urllib.parse import quote

import musicbrainzngs
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from beets_flask.library_cache import (
    invalidate_artists_cache,
    invalidate_artists_list_cache,
    get_json_cache,
    set_json_cache,
    get_db_missing_cache,
    set_db_missing_cache,
)
from beets_flask.logger import log
from beets_flask.server.exceptions import NotFoundException
# All pure business-logic helpers are framework-agnostic — reuse directly.
from beets_flask.server.routes.library.artists import (
    ARTISTS_CACHE_TTL_SECONDS,
    MISSING_CACHE_TTL_SECONDS,
    _artists_cache_key,
    _best_release_tracks_for_group,
    _clean_cached_missing_payload,
    _missing_cache_key,
    ensure_missing_cache_warmed_for_all_artists,
    get_artists_pandas,
    recompute_missing_cache_for_artist,
)
from beets_flask.server_v2.dependencies import BeetsLib

router = APIRouter(tags=["library"])


# NOTE: specific routes (with literal path suffixes) registered BEFORE
# the wildcard {artist_name:path} routes to avoid greedy matching.


@router.post("/artists/missing/cache/warm-all")
async def warm_all_missing_albums_cache(lib: BeetsLib, force: bool = False) -> dict:
    result = ensure_missing_cache_warmed_for_all_artists(lib=lib, force_recompute=force)
    return result


@router.post("/artists/cache/refresh")
async def refresh_artists_cache() -> dict:
    cleared = invalidate_artists_cache()
    return {"ok": True, "cleared": cleared}


@router.get("/missing-album-tracks")
async def missing_album_tracks(id: str = "") -> list:
    if not id:
        raise HTTPException(status_code=400, detail="id is required")

    if id.startswith("deezer:"):
        deezer_id = id[7:]
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"https://api.deezer.com/album/{deezer_id}/tracks", timeout=8
            ) as req:
                data = json.loads(req.read())
            return [
                {
                    "title": t.get("title", ""),
                    "duration": t.get("duration"),
                    "track_position": t.get("track_position"),
                }
                for t in data.get("data", [])
            ]
        except Exception:
            return []
    else:
        try:
            return _best_release_tracks_for_group(id)
        except Exception:
            return []


@router.get("/artists/{artist_name:path}/missing")
async def missing_albums_by_artist(artist_name: str, lib: BeetsLib, refresh: bool = False) -> Response:
    cache_key = _missing_cache_key(artist_name)
    log.info("missing_albums request artist=%s refresh=%s", artist_name, refresh)

    if not refresh:
        cached = get_json_cache(cache_key)
        if cached is not None:
            cached, changed = _clean_cached_missing_payload(artist_name, cached, lib=lib)
            if changed:
                set_json_cache(cache_key, cached, MISSING_CACHE_TTL_SECONDS)
            set_db_missing_cache(artist_name, cached)
            log.info("missing_albums redis_hit artist=%s", artist_name)
            return Response(content=cached, media_type="application/json")

        log.info("missing_albums redis_miss artist=%s", artist_name)
        db_cached = get_db_missing_cache(artist_name)
        if db_cached is not None:
            db_cached, changed = _clean_cached_missing_payload(artist_name, db_cached, lib=lib)
            log.info("missing_albums db_hit artist=%s", artist_name)
            set_json_cache(cache_key, db_cached, MISSING_CACHE_TTL_SECONDS)
            if changed:
                set_db_missing_cache(artist_name, db_cached)
            return Response(content=db_cached, media_type="application/json")
        log.info("missing_albums db_miss artist=%s", artist_name)
    else:
        log.info("missing_albums force_refresh artist=%s", artist_name)

    invalidate_artists_list_cache()
    try:
        missing = recompute_missing_cache_for_artist(artist_name, lib=lib)
    except musicbrainzngs.musicbrainz.MusicBrainzError as exc:
        log.warning("missing_albums musicbrainz_error artist=%s error=%s", artist_name, exc)
        return Response(content="[]", media_type="application/json")

    payload = pd.DataFrame(missing).to_json(orient="records")
    log.info("missing_albums computed artist=%s count=%s", artist_name, len(missing))
    return Response(content=payload, media_type="application/json")


@router.get("/artists/{artist_name:path}")
async def artist_by_name(artist_name: str, lib: BeetsLib) -> Response:
    return await _get_artists(artist_name, lib)


@router.get("/artists")
async def all_artists(lib: BeetsLib) -> Response:
    return await _get_artists(None, lib)


async def _get_artists(artist_name: str | None, lib) -> Response:
    import unicodedata

    from beets_flask.library_cache import get_missing_count_map

    cache_key = _artists_cache_key(artist_name)
    cached = get_json_cache(cache_key)
    if cached is not None:
        return Response(content=cached, media_type="application/json")

    artists_albums = (
        get_artists_pandas("albums", artist_name, lib=lib)
        .rename(columns={"count": "album_count", "last_added": "last_album_added", "first_added": "first_album_added"})
        .set_index("artist")
    )
    artists_items = (
        get_artists_pandas("items", artist_name, include_size=True, lib=lib)
        .rename(columns={"count": "item_count", "last_added": "last_item_added", "first_added": "first_item_added"})
        .set_index("artist")
    )

    artists = artists_albums.join(artists_items, how="outer").reset_index()
    artists["album_count"] = artists["album_count"].fillna(0).astype(int)
    artists["item_count"] = artists["item_count"].fillna(0).astype(int)
    artists["total_size"] = artists["total_size"].fillna(0).astype(int)

    missing_count_map = get_missing_count_map()
    artists["missing_count"] = (
        artists["artist"]
        .apply(lambda n: missing_count_map.get(unicodedata.normalize("NFC", str(n)).strip(), 0))
        .fillna(0)
        .astype(int)
    )

    if artist_name is not None:
        if artists.empty:
            from beets_flask.discovery.followed_artists import is_followed

            if is_followed(artist_name):
                stub = {
                    "artist": artist_name,
                    "album_count": 0,
                    "item_count": 0,
                    "total_size": 0,
                    "missing_count": 0,
                    "followed": True,
                }
                return Response(content=json.dumps(stub), media_type="application/json")
            raise NotFoundException(f"Artist '{artist_name}' not found.")

        payload = artists.iloc[0].to_json()
        set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
        return Response(content=payload, media_type="application/json")

    payload = artists.to_json(orient="records")
    set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
    return Response(content=payload, media_type="application/json")
