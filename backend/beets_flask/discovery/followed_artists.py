"""SQLite-backed per-user storage for followed artists."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from beets_flask.database.models.users import UserArtistFollowInDb, UserInDb
from beets_flask.database.setup import db_session_factory


def _get_row(session, user_id: str, name: str) -> UserArtistFollowInDb | None:
    return session.execute(
        select(UserArtistFollowInDb).where(
            UserArtistFollowInDb.user_id == user_id,
            UserArtistFollowInDb.artist_name == name,
        )
    ).scalars().first()


def _propagate_new_artist(
    session, actor_id: str, artist_name: str, now: str, display_name: str | None = None
) -> None:
    all_users = session.execute(select(UserInDb)).scalars().all()
    for u in all_users:
        if _get_row(session, u.id, artist_name) is None:
            row = UserArtistFollowInDb(
                user_id=u.id,
                artist_name=artist_name,
                is_following=(u.id == actor_id),
                added_at=now,
                display_name=display_name,
            )
            session.add(row)


def follow_artist(user_id: str, name: str, display_name: str | None = None) -> dict:
    """Follow an artist for the given user.  Propagates to all users if new."""
    now = datetime.now(UTC).isoformat()
    with db_session_factory() as session:
        row = _get_row(session, user_id, name)
        if row is None:
            _propagate_new_artist(session, user_id, name, now, display_name=display_name)
        else:
            row.is_following = True
            if display_name:
                row.display_name = display_name
        session.commit()
    return {"name": name, "added_at": now, "display_name": display_name}


def unfollow_artist(user_id: str, name: str) -> bool:
    """Unfollow an artist for the given user.  Returns True if it was followed."""
    with db_session_factory() as session:
        row = _get_row(session, user_id, name)
        if row and row.is_following:
            row.is_following = False
            session.commit()
            return True
    return False


def get_followed_artists(user_id: str) -> list[dict]:
    """Return artists followed by this user, sorted alphabetically."""
    with db_session_factory() as session:
        rows = session.execute(
            select(UserArtistFollowInDb).where(
                UserArtistFollowInDb.user_id == user_id,
                UserArtistFollowInDb.is_following == True,  # noqa: E712
            ).order_by(UserArtistFollowInDb.artist_name)
        ).scalars().all()
        return [{"name": r.artist_name, "added_at": r.added_at, "display_name": r.display_name} for r in rows]


def is_followed(user_id: str, name: str) -> bool:
    with db_session_factory() as session:
        row = _get_row(session, user_id, name)
        return row is not None and row.is_following
