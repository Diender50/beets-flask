"""Album tag editing endpoint.

PATCH /album/{album_id}/tags
  - Applies album-level and per-track field changes.
  - Writes tags to audio files via beets try_sync.
  - For Vorbis-based formats (FLAC, OGG, OPUS) writes ALBUMARTISTS/ARTISTS
    as native multi-valued tags via mutagen directly (beets serialises them
    as a single ';'-joined string which loses the multi-value structure).
  - Singular albumartist/artist is formatted as
    "A feat. B", "A feat. B & C", "A feat. B, C & D", etc.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mutagen
from beets import util as beets_util
from beets.library import Album, Item
from fastapi import APIRouter
from mutagen._vorbis import VComment
from pydantic import BaseModel

from beets_flask.config import get_config
from beets_flask.logger import log
from beets_flask.server.dependencies import BeetsLib, require_permission
from beets_flask.server.exceptions import InvalidUsageException, NotFoundException

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _format_feat(artists: list[str]) -> str:
    """Format a list of artists into a 'main feat. others' display string."""
    artists = [a for a in artists if a]
    if not artists:
        return ""
    if len(artists) == 1:
        return artists[0]
    main = artists[0]
    featured = artists[1:]
    if len(featured) == 1:
        others = featured[0]
    elif len(featured) == 2:
        others = f"{featured[0]} & {featured[1]}"
    else:
        others = ", ".join(featured[:-1]) + f" & {featured[-1]}"
    return f"{main} feat. {others}"


def _write_multivalued(path: bytes, albumartists: list[str], artists: list[str]) -> None:
    """Overwrite ALBUMARTISTS/ARTISTS as separate tag entries (Vorbis only).

    Beets serialises list fields as a single ';'-joined string. For Vorbis-
    based formats (FLAC, OGG, OPUS) mutagen supports true multi-valued tags
    by assigning a Python list — each element becomes its own tag entry.
    ID3/MP3 has no standard multi-value for these fields so we leave it as-is.
    """
    try:
        audio = mutagen.File(beets_util.syspath(path))
    except Exception as exc:
        log.warning(f"mutagen could not open {path!r}: {exc}")
        return

    if audio is None or audio.tags is None:
        return

    if not isinstance(audio.tags, VComment):
        return  # MP3/ID3 — leave beets' semicolon-joined format

    changed = False
    if albumartists:
        audio.tags["ALBUMARTISTS"] = albumartists
        changed = True
    if artists:
        audio.tags["ARTISTS"] = artists
        changed = True

    if changed:
        try:
            audio.save()
        except Exception as exc:
            log.warning(f"mutagen save failed for {path!r}: {exc}")


# ── Request models ────────────────────────────────────────────────────────────


class TrackTagUpdate(BaseModel):
    id: int
    name: str | None = None         # frontend 'name' = beets 'title'
    artists: list[str] | None = None
    track: int | None = None


class AlbumTagsBody(BaseModel):
    album: str | None = None
    albumartists: list[str] | None = None
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
    _user: require_permission("can_retag"),
) -> dict[str, Any]:
    if get_config()["gui"]["library"]["readonly"].get(bool):
        raise InvalidUsageException("Library is read-only")

    album_obj: Album | None = lib.get_album(album_id)
    if album_obj is None:
        raise NotFoundException(f"Album {album_id} not found")

    items: list[Item] = list(album_obj.items())

    new_albumartist: str | None = None
    if body.albumartists is not None:
        new_albumartist = _format_feat(body.albumartists)

    needs_move = (
        (body.album is not None and body.album != album_obj.album) or
        (new_albumartist is not None and new_albumartist != album_obj.albumartist)
    )

    track_map = {t.id: t for t in body.tracks}

    def _sync() -> None:
        for item in items:
            # Album-level fields
            if body.album is not None:
                item["album"] = body.album
            if body.albumartists is not None:
                item["albumartists"] = body.albumartists
                item["albumartist"] = new_albumartist
            if body.year is not None:
                item["year"] = body.year
            if body.genre is not None:
                item["genre"] = body.genre
            if body.label is not None:
                item["label"] = body.label

            # Per-track overrides
            effective_artists: list[str] | None = None
            track_upd = track_map.get(item.id)
            if track_upd is not None:
                if track_upd.name is not None:
                    item["title"] = track_upd.name
                if track_upd.artists is not None:
                    item["artists"] = track_upd.artists
                    item["artist"] = _format_feat(track_upd.artists)
                    effective_artists = track_upd.artists
                if track_upd.track is not None:
                    item["track"] = track_upd.track

            # Write tags to file (try_write has its own error handling)
            item.try_write()
            item.store()

            # Move file to new path if directory/filename changed
            if needs_move:
                try:
                    item.move(with_album=False)
                    item.store()
                except Exception as exc:
                    log.warning(
                        f"Could not move item {item.id} "
                        f"(tags written, rename skipped): {exc}"
                    )

            # For Vorbis files: overwrite with native multi-valued tags,
            # then re-read the file so the DB reflects exactly what's on disk.
            needs_multival = body.albumartists is not None or effective_artists is not None
            if needs_multival:
                _write_multivalued(
                    item.path,
                    albumartists=body.albumartists or [],
                    artists=effective_artists or [],
                )
                item.read()
                item.store()

        # Keep album-level DB object in sync
        if body.album is not None:
            album_obj["album"] = body.album
        if body.albumartists is not None:
            album_obj["albumartists"] = body.albumartists
            album_obj["albumartist"] = new_albumartist
        if body.year is not None:
            album_obj["year"] = body.year
        if body.genre is not None:
            album_obj["genre"] = body.genre
        if body.label is not None:
            album_obj["label"] = body.label
        album_obj.store()

    await asyncio.to_thread(_sync)

    log.info(
        f"Tags updated for album {album_id} "
        f"({len(items)} tracks, moved={needs_move})"
    )
    return {"ok": True, "album_id": album_id, "moved": needs_move}
