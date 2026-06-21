"""New-album notification system.

Follow/unfollow is entirely independent from the TrackedArtist concept.
It only controls whether the notification worker checks for new releases.

Workflow:
  1. `check_all_followed_artists()` runs on a schedule (every N hours).
  2. For each followed artist, fetch fresh discography via MB + Deezer.
  3. Diff against the stored `ArtistDiscographySnapshot`.
  4. New keys → insert `ArtistNewAlbumNotification` rows.
  5. Update snapshot.

First-time check (no snapshot yet): populate snapshot without notifying.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from beets_flask.database.models.notifications import (
    ArtistDiscographySnapshot,
    ArtistNewAlbumNotification,
    ArtistNotificationSubscription,
)
from beets_flask.database.setup import db_session_factory
from beets_flask.logger import log


# ── Subscription CRUD ─────────────────────────────────────────────────────────


def follow_artist(artist_name: str) -> bool:
    """Subscribe artist to notifications. Returns True if newly added."""
    with db_session_factory() as session:
        existing = session.execute(
            select(ArtistNotificationSubscription).where(
                ArtistNotificationSubscription.artist_name == artist_name
            )
        ).scalars().first()
        if existing:
            return False
        session.add(ArtistNotificationSubscription(artist_name=artist_name))
        session.commit()
        return True


def unfollow_artist(artist_name: str) -> bool:
    """Unsubscribe artist from notifications and delete all their notifications. Returns True if row existed."""
    with db_session_factory() as session:
        row = session.execute(
            select(ArtistNotificationSubscription).where(
                ArtistNotificationSubscription.artist_name == artist_name
            )
        ).scalars().first()
        if row is None:
            return False
        session.delete(row)
        # cascade: delete all notifications for this artist
        notifs = session.execute(
            select(ArtistNewAlbumNotification).where(
                ArtistNewAlbumNotification.artist_name == artist_name
            )
        ).scalars().all()
        for n in notifs:
            session.delete(n)
        # also clear the discography snapshot so a re-follow starts fresh
        snap = session.execute(
            select(ArtistDiscographySnapshot).where(
                ArtistDiscographySnapshot.artist_name == artist_name
            )
        ).scalars().first()
        if snap:
            session.delete(snap)
        session.commit()
        return True


def get_followed_artist_names() -> list[str]:
    """Return all artist names subscribed to notifications."""
    with db_session_factory() as session:
        rows = session.execute(
            select(ArtistNotificationSubscription).order_by(
                ArtistNotificationSubscription.artist_name
            )
        ).scalars().all()
        return [r.artist_name for r in rows]


def is_followed(artist_name: str) -> bool:
    with db_session_factory() as session:
        return session.execute(
            select(ArtistNotificationSubscription).where(
                ArtistNotificationSubscription.artist_name == artist_name
            )
        ).scalars().first() is not None


def _album_key(album: dict) -> str | None:
    """Return the stable identity key for an album entry, or None if unknown."""
    rgid = album.get("mb_releasegroupid")
    return str(rgid) if rgid else None


def _load_snapshot(session, artist_name: str) -> set[str] | None:
    """Return stored album keys, or None if no snapshot exists yet."""
    row = session.execute(
        select(ArtistDiscographySnapshot).where(
            ArtistDiscographySnapshot.artist_name == artist_name
        )
    ).scalars().first()
    if row is None:
        return None
    try:
        keys = json.loads(row.album_keys_json)
        return set(keys) if isinstance(keys, list) else set()
    except Exception:
        return set()


def _save_snapshot(session, artist_name: str, keys: set[str]) -> None:
    row = session.execute(
        select(ArtistDiscographySnapshot).where(
            ArtistDiscographySnapshot.artist_name == artist_name
        )
    ).scalars().first()
    now = datetime.now(UTC)
    if row is None:
        session.add(
            ArtistDiscographySnapshot(
                artist_name=artist_name,
                album_keys_json=json.dumps(sorted(keys)),
                snapshot_at=now,
            )
        )
    else:
        row.album_keys_json = json.dumps(sorted(keys))
        row.snapshot_at = now


def _insert_notification(session, artist_name: str, album: dict) -> bool:
    """Insert one notification. Returns True if inserted, False if already exists."""
    key = _album_key(album)
    if not key:
        return False
    try:
        session.add(
            ArtistNewAlbumNotification(
                artist_name=artist_name,
                album_key=key,
                album_json=json.dumps(album),
            )
        )
        session.flush()
        return True
    except IntegrityError:
        session.rollback()
        return False


def _check_artist(artist_name: str) -> int:
    """Check one artist for new albums. Returns count of new notifications created."""
    from beets_flask.server.routes.library.artists import _missing_albums_from_sources

    try:
        fresh = _missing_albums_from_sources(artist_name)
    except Exception as exc:
        log.warning("notifications: fetch failed artist=%s error=%s", artist_name, exc)
        return 0

    fresh_by_key: dict[str, dict] = {}
    for album in fresh:
        key = _album_key(album)
        if key:
            fresh_by_key[key] = album
    fresh_keys = set(fresh_by_key)

    with db_session_factory() as session:
        prev_keys = _load_snapshot(session, artist_name)

        if prev_keys is None:
            # First check: seed snapshot, no notifications
            _save_snapshot(session, artist_name, fresh_keys)
            session.commit()
            log.debug("notifications: seeded snapshot artist=%s count=%d", artist_name, len(fresh_keys))
            return 0

        new_keys = fresh_keys - prev_keys
        count = 0
        for key in new_keys:
            if _insert_notification(session, artist_name, fresh_by_key[key]):
                count += 1
                log.info(
                    "notifications: new album artist=%s album=%s key=%s",
                    artist_name,
                    fresh_by_key[key].get("album"),
                    key,
                )

        _save_snapshot(session, artist_name, fresh_keys)
        session.commit()

    return count


def check_all_followed_artists() -> int:
    """Run a notification check for every followed artist. Returns total new notifications."""
    names = get_followed_artist_names()
    total = 0
    for name in names:
        total += _check_artist(name)
    if total:
        log.info("notifications: check complete new_total=%d", total)
    else:
        log.debug("notifications: check complete, no new albums")
    return total


# ── REST helpers ──────────────────────────────────────────────────────────────


def get_unseen_notifications() -> list[dict]:
    """Return all unseen notifications, newest first."""
    with db_session_factory() as session:
        rows = session.execute(
            select(ArtistNewAlbumNotification)
            .where(ArtistNewAlbumNotification.seen_at.is_(None))
            .order_by(ArtistNewAlbumNotification.created_at.desc())
        ).scalars().all()
        return [_notification_to_dict(r) for r in rows]


def get_all_notifications(limit: int = 50) -> list[dict]:
    """Return recent notifications (seen + unseen), newest first."""
    with db_session_factory() as session:
        rows = session.execute(
            select(ArtistNewAlbumNotification)
            .order_by(ArtistNewAlbumNotification.created_at.desc())
            .limit(limit)
        ).scalars().all()
        return [_notification_to_dict(r) for r in rows]


def mark_seen(ids: list[str] | None = None) -> int:
    """Mark notifications as seen. Pass ids=None to mark all unseen. Returns count updated."""
    now = datetime.now(UTC)
    with db_session_factory() as session:
        query = select(ArtistNewAlbumNotification).where(
            ArtistNewAlbumNotification.seen_at.is_(None)
        )
        if ids is not None:
            query = query.where(ArtistNewAlbumNotification.id.in_(ids))
        rows = session.execute(query).scalars().all()
        for row in rows:
            row.seen_at = now
        session.commit()
        return len(rows)


def get_unseen_count() -> int:
    """Fast count of unseen notifications (used for badge)."""
    with db_session_factory() as session:
        from sqlalchemy import func
        result = session.execute(
            select(func.count()).select_from(ArtistNewAlbumNotification).where(
                ArtistNewAlbumNotification.seen_at.is_(None)
            )
        ).scalar()
        return int(result or 0)


def _notification_to_dict(row: ArtistNewAlbumNotification) -> dict:
    try:
        album = json.loads(row.album_json)
    except Exception:
        album = {}
    return {
        "id": row.id,
        "artist_name": row.artist_name,
        "album_key": row.album_key,
        "album": album,
        "seen": row.seen_at is not None,
        "seen_at": row.seen_at.isoformat() if row.seen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
