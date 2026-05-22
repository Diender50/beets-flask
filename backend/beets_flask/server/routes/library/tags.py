"""Album tag editing endpoint.

PATCH /album/{album_id}/tags
  - Applies album-level and per-track field changes.
  - Writes tags to audio files via beets try_sync.
  - Runs beet move when albumartist or album title changed.
"""

from __future__ import annotations

from typing import Any

from beets.library import Album, Item
from fastapi import APIRouter
from pydantic import BaseModel

from beets_flask.config import get_config
from beets_flask.logger import log
from beets_flask.server.dependencies import BeetsLib
from beets_flask.server.exceptions import InvalidUsageException, NotFoundException

router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────


class TrackTagUpdate(BaseModel):
    id: int
    name: str | None = None     # frontend 'name' = beets 'title'
    artist: str | None = None
    track: int | None = None


class AlbumTagsBody(BaseModel):
    album: str | None = None
    albumartist: str | None = None
    year: int | None = None
    genre: str | None = None
    label: str | None = None
    tracks: list[TrackTagUpdate] = []


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.patch("/album/{album_id}/tags")
async def update_album_tags(
    album_id: int,
    body: AlbumTagsBody,
    lib: BeetsLib,
) -> dict[str, Any]:
    if get_config()["gui"]["library"]["readonly"].get(bool):
        raise InvalidUsageException("Library is read-only")

    album_obj: Album | None = lib.get_album(album_id)
    if album_obj is None:
        raise NotFoundException(f"Album {album_id} not found")

    items: list[Item] = list(album_obj.items())

    # Determine if files need to move (path template depends on album/albumartist)
    needs_move = (
        (body.album is not None and body.album != album_obj.album) or
        (body.albumartist is not None and body.albumartist != album_obj.albumartist)
    )

    track_map = {t.id: t for t in body.tracks}

    # ── Apply changes to each item ────────────────────────────────────────────
    for item in items:
        # Album-level fields propagated to all tracks
        if body.album is not None:
            item["album"] = body.album
        if body.albumartist is not None:
            item["albumartist"] = body.albumartist
        if body.year is not None:
            item["year"] = body.year
        if body.genre is not None:
            item["genre"] = body.genre
        if body.label is not None:
            item["label"] = body.label

        # Per-track overrides
        track_upd = track_map.get(item.id)
        if track_upd is not None:
            if track_upd.name is not None:
                item["title"] = track_upd.name
            if track_upd.artist is not None:
                item["artist"] = track_upd.artist
            if track_upd.track is not None:
                item["track"] = track_upd.track

        # Write tags to file; move file if path template changed
        item.try_sync(write=True, move=needs_move, with_album=False)

    # ── Update album object in DB ─────────────────────────────────────────────
    if body.album is not None:
        album_obj["album"] = body.album
    if body.albumartist is not None:
        album_obj["albumartist"] = body.albumartist
    if body.year is not None:
        album_obj["year"] = body.year
    if body.genre is not None:
        album_obj["genre"] = body.genre
    if body.label is not None:
        album_obj["label"] = body.label
    album_obj.store()

    log.info(
        f"Tags updated for album {album_id} "
        f"({len(items)} tracks, moved={needs_move})"
    )
    return {"ok": True, "album_id": album_id, "moved": needs_move}
