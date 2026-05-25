"""User management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from beets_flask.database.models.users import (
    QUALITY_LEVELS,
    UserInDb,
)
from beets_flask.server.auth_utils import hash_password
from beets_flask.server.dependencies import CurrentUser, DbSession, RequireAdmin
from beets_flask.server.exceptions import (
    IntegrityException,
    InvalidUsageException,
    NotFoundException,
)

router = APIRouter(tags=["users"])


# ── Request / response models ─────────────────────────────────────────────────


class CreateUserBody(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    can_auto_download: bool = False
    can_manual_download: bool = True
    can_retag: bool = True
    can_delete: bool = False
    can_add_artist: bool = True
    max_quality: str = "flac"


class UpdateUserBody(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None
    can_auto_download: bool | None = None
    can_manual_download: bool | None = None
    can_retag: bool | None = None
    can_delete: bool | None = None
    can_add_artist: bool | None = None
    max_quality: str | None = None
    password: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_to_dict(user: UserInDb) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "can_auto_download": user.can_auto_download,
        "can_manual_download": user.can_manual_download,
        "can_retag": user.can_retag,
        "can_delete": user.can_delete,
        "can_add_artist": user.can_add_artist,
        "max_quality": user.max_quality,
    }



# ── Admin: user CRUD ──────────────────────────────────────────────────────────


@router.get("/users")
async def list_users(
    _admin: RequireAdmin,
    db: DbSession,
) -> list[dict[str, Any]]:
    users = db.execute(select(UserInDb).order_by(UserInDb.username)).scalars().all()
    return [_user_to_dict(u) for u in users]


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserBody,
    _admin: RequireAdmin,
    db: DbSession,
) -> dict[str, Any]:
    username = body.username.strip()
    if not username or not body.password:
        raise InvalidUsageException("username and password are required")

    if body.max_quality not in QUALITY_LEVELS:
        raise InvalidUsageException(f"max_quality must be one of {QUALITY_LEVELS}")

    existing = db.execute(
        select(UserInDb).where(UserInDb.username == username)
    ).scalars().first()
    if existing is not None:
        raise IntegrityException(f"Username '{username}' already taken")

    user = UserInDb(
        username=username,
        hashed_password=hash_password(body.password),
        is_admin=body.is_admin,
        can_auto_download=body.can_auto_download,
        can_manual_download=body.can_manual_download,
        can_retag=body.can_retag,
        can_delete=body.can_delete,
        can_add_artist=body.can_add_artist,
        max_quality=body.max_quality,
    )
    db.add(user)
    return _user_to_dict(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserBody,
    _admin: RequireAdmin,
    db: DbSession,
) -> dict[str, Any]:
    user = db.get(UserInDb, user_id)
    if user is None:
        raise NotFoundException(f"User {user_id} not found")

    if body.max_quality is not None and body.max_quality not in QUALITY_LEVELS:
        raise InvalidUsageException(f"max_quality must be one of {QUALITY_LEVELS}")

    demoting_admin = body.is_admin is False and user.is_admin
    deactivating_admin = body.is_active is False and user.is_active and user.is_admin
    if demoting_admin or deactivating_admin:
        other_active_admins = (
            db.execute(
                select(UserInDb).where(
                    UserInDb.is_admin.is_(True),
                    UserInDb.is_active.is_(True),
                    UserInDb.id != user_id,
                )
            )
            .scalars()
            .first()
        )
        if other_active_admins is None:
            raise InvalidUsageException("Cannot remove last active admin")

    for field in (
        "is_active", "is_admin", "can_auto_download", "can_manual_download",
        "can_retag", "can_delete", "can_add_artist", "max_quality",
    ):
        val = getattr(body, field)
        if val is not None:
            setattr(user, field, val)

    if body.password is not None:
        if len(body.password.strip()) < 6:
            raise InvalidUsageException("Password must be at least 6 characters")
        user.hashed_password = hash_password(body.password)

    return _user_to_dict(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    admin: RequireAdmin,
    db: DbSession,
) -> None:
    if user_id == admin.id:
        raise InvalidUsageException("Cannot delete your own account")

    user = db.get(UserInDb, user_id)
    if user is None:
        raise NotFoundException(f"User {user_id} not found")

    if user.is_admin:
        other_active_admins = (
            db.execute(
                select(UserInDb).where(
                    UserInDb.is_admin.is_(True),
                    UserInDb.is_active.is_(True),
                    UserInDb.id != user_id,
                )
            )
            .scalars()
            .first()
        )
        if other_active_admins is None:
            raise InvalidUsageException("Cannot deactivate last active admin")

    # Soft-delete: deactivate rather than hard-delete to preserve follow history
    user.is_active = False


