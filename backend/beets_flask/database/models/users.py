"""User account models."""

from __future__ import annotations

from sqlalchemy import ForeignKey, UniqueConstraint
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


class UserArtistFollowInDb(Base):
    """Per-user follow state for an artist.

    A row exists for every (user, artist) pair that has been introduced to the
    system.  `is_following=True` means the user actively follows the artist;
    `False` means the artist was introduced by someone else and the user has
    not yet followed it.
    """

    __tablename__ = "user_artist_follow"
    __table_args__ = (UniqueConstraint("user_id", "artist_name"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("user.id"), index=True, nullable=False)
    artist_name: Mapped[str] = mapped_column(index=True, nullable=False)
    is_following: Mapped[bool] = mapped_column(default=False)
    added_at: Mapped[str] = mapped_column()  # ISO-8601

    def __init__(
        self,
        user_id: str,
        artist_name: str,
        is_following: bool = False,
        added_at: str = "",
    ):
        super().__init__()
        self.user_id = user_id
        self.artist_name = artist_name
        self.is_following = is_following
        self.added_at = added_at
