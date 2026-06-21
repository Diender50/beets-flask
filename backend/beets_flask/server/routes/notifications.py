"""REST endpoints for new-album notifications."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from beets_flask.notifications import (
    get_all_notifications,
    get_unseen_count,
    get_unseen_notifications,
    mark_seen,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(unseen_only: bool = False, limit: int = 50) -> list[dict]:
    if unseen_only:
        return get_unseen_notifications()
    return get_all_notifications(limit=limit)


@router.get("/count")
async def unseen_count() -> dict:
    return {"unseen": get_unseen_count()}


@router.post("/seen")
async def mark_notifications_seen(
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict:
    """Mark notifications as seen.

    Body: ``{"ids": ["uuid1", ...]}`` to mark specific ones,
          ``{}`` or ``{"all": true}`` to mark all unseen.
    """
    ids: list[str] | None = None
    if data.get("ids") is not None:
        raw = data["ids"]
        if not isinstance(raw, list):
            raise HTTPException(status_code=400, detail="ids must be a list")
        ids = [str(i) for i in raw]
    updated = mark_seen(ids=ids)
    return {"updated": updated}


@router.post("/check")
async def trigger_check() -> dict:
    """Manually trigger a notification check for all followed artists. Use for testing."""
    from beets_flask.notifications import check_all_followed_artists
    total = check_all_followed_artists()
    return {"new_notifications": total}


@router.post("/debug/inject/{artist_name}")
async def inject_test_notification(artist_name: str) -> dict:
    """Insert a fake notification for an artist. Use for UI testing only."""
    import time
    from beets_flask.database.models.notifications import ArtistNewAlbumNotification
    from beets_flask.database.setup import db_session_factory

    fake_key = f"debug:test-album-{int(time.time())}"
    fake_album = {
        "album": "[TEST] New Album",
        "year": 2025,
        "cover_url": None,
        "release_type": "Album",
        "mb_releasegroupid": fake_key,
    }
    with db_session_factory() as session:
        session.add(ArtistNewAlbumNotification(
            artist_name=artist_name,
            album_key=fake_key,
            album_json=json.dumps(fake_album),
        ))
        session.commit()
    return {"ok": True, "artist_name": artist_name, "album_key": fake_key}
