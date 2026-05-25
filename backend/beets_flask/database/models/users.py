"""User account models."""

from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from beets_flask.database.models.base import Base

QUALITY_LEVELS = ["flac", "high_lossy", "med_lossy", "low_lossy"]


class UserInDb(Base):
    """A beets-flask user account."""

    __tablename__ = "user"

    username: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    can_auto_download: Mapped[bool] = mapped_column(default=False)
    can_manual_download: Mapped[bool] = mapped_column(default=True)
    can_retag: Mapped[bool] = mapped_column(default=True)
    can_delete: Mapped[bool] = mapped_column(default=False)
    can_add_artist: Mapped[bool] = mapped_column(default=True)
    # Highest quality tier this user may download.
    # Hierarchy (best→worst): flac > high_lossy > med_lossy > low_lossy
    max_quality: Mapped[str] = mapped_column(default="flac")

    def __init__(
        self,
        username: str,
        hashed_password: str,
        is_active: bool = True,
        is_admin: bool = False,
        can_auto_download: bool = False,
        can_manual_download: bool = True,
        can_retag: bool = True,
        can_delete: bool = False,
        can_add_artist: bool = True,
        max_quality: str = "flac",
    ):
        super().__init__()
        self.username = username
        self.hashed_password = hashed_password
        self.is_active = is_active
        self.is_admin = is_admin
        self.can_auto_download = can_auto_download
        self.can_manual_download = can_manual_download
        self.can_retag = can_retag
        self.can_delete = can_delete
        self.can_add_artist = can_add_artist
        self.max_quality = max_quality


class TrackedArtistInDb(Base):
    """Global tracked-artist list shared across all users.

    `artist_name` is the primary display name (EN/FR primary alias when one
    exists, otherwise the original MusicBrainz name).
    `original_name` stores the raw MusicBrainz name when it differs from
    `artist_name`; used only as a fallback for download-provider searches.
    """

    __tablename__ = "tracked_artist"

    artist_name: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    original_name: Mapped[str | None] = mapped_column(nullable=True, default=None)
    added_at: Mapped[str] = mapped_column()  # ISO-8601

    def __init__(
        self,
        artist_name: str,
        added_at: str = "",
        original_name: str | None = None,
    ):
        super().__init__()
        self.artist_name = artist_name
        self.original_name = original_name
        self.added_at = added_at
