"""DB models for new-album notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from beets_flask.database.models.base import Base


class ArtistNotificationSubscription(Base):
    """Artist the user wants new-album notifications for.

    Completely independent from TrackedArtistInDb.
    Follow/unfollow only writes here — never touches the tracked_artist table.
    """

    __tablename__ = "artist_notification_subscription"

    artist_name: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)

    def __init__(self, artist_name: str):
        super().__init__()
        self.artist_name = artist_name


class ArtistDiscographySnapshot(Base):
    """Last-known set of album keys per tracked artist.

    Written only by the notification worker; never touched by imports.
    Compared against a fresh fetch to detect new releases.
    """

    __tablename__ = "artist_discography_snapshot"

    artist_name: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    # JSON-serialised list[str] of mb_releasegroupid / "deezer:<id>" keys
    album_keys_json: Mapped[str] = mapped_column(nullable=False, default="[]")
    snapshot_at: Mapped[datetime] = mapped_column(nullable=False)

    def __init__(self, artist_name: str, album_keys_json: str, snapshot_at: datetime):
        super().__init__()
        self.artist_name = artist_name
        self.album_keys_json = album_keys_json
        self.snapshot_at = snapshot_at


class ArtistNewAlbumNotification(Base):
    """One unseen new-album notification for a tracked artist."""

    __tablename__ = "artist_new_album_notification"
    __table_args__ = (
        UniqueConstraint("artist_name", "album_key", name="uq_notif_artist_album"),
    )

    artist_name: Mapped[str] = mapped_column(index=True, nullable=False)
    album_key: Mapped[str] = mapped_column(nullable=False)  # mb_releasegroupid or "deezer:<id>"
    album_json: Mapped[str] = mapped_column(nullable=False)  # full album dict as JSON
    seen_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)

    def __init__(self, artist_name: str, album_key: str, album_json: str):
        super().__init__()
        self.artist_name = artist_name
        self.album_key = album_key
        self.album_json = album_json
        self.seen_at = None
