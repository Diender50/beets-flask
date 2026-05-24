"""Auth endpoints: register (bootstrap), login, me, change-password."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from beets_flask.database.models.users import UserInDb
from beets_flask.server.auth_utils import create_token, hash_password, verify_password
from beets_flask.server.dependencies import CurrentUser, DbSession
from beets_flask.server.exceptions import (
    ForbiddenException,
    InvalidUsageException,
    UnauthorizedException,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / response models ─────────────────────────────────────────────────


class LoginBody(BaseModel):
    username: str
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


class RegisterBody(BaseModel):
    username: str
    password: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _user_to_dict(user: UserInDb) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "can_auto_download": user.can_auto_download,
        "can_manual_download": user.can_manual_download,
        "can_retag": user.can_retag,
        "can_delete": user.can_delete,
        "can_add_artist": user.can_add_artist,
        "max_quality": user.max_quality,
    }


def _make_token(user: UserInDb) -> str:
    from beets_flask.config.flask_config import get_flask_config

    cfg = get_flask_config()
    return create_token(user.id, cfg.SECRET_KEY, cfg.JWT_EXPIRY_HOURS)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/needs-setup")
async def needs_setup(db: DbSession) -> dict[str, Any]:
    """Public: true when zero users exist (first-run setup required)."""
    count = db.execute(select(func.count()).select_from(UserInDb)).scalar() or 0
    return {"needs_setup": count == 0}


@router.post("/register", status_code=201)
async def register(body: RegisterBody, db: DbSession) -> dict[str, Any]:
    """Create the first user (admin).  Fails if any user already exists."""
    count = db.execute(select(func.count()).select_from(UserInDb)).scalar() or 0
    if count > 0:
        raise ForbiddenException(
            "Registration is closed. Ask an admin to create your account."
        )

    username = body.username.strip()
    if not username or not body.password:
        raise InvalidUsageException("username and password are required")

    user = UserInDb(
        username=username,
        hashed_password=hash_password(body.password),
        is_admin=True,
        can_delete=True,
        can_auto_download=True,
    )
    db.add(user)
    db.flush()  # populate user.id before token creation
    token = _make_token(user)
    return {"token": token, "user": _user_to_dict(user)}


@router.post("/login")
async def login(body: LoginBody, db: DbSession) -> dict[str, Any]:
    stmt = select(UserInDb).where(UserInDb.username == body.username)
    user: UserInDb | None = db.execute(stmt).scalars().first()

    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedException("Invalid credentials")

    token = _make_token(user)
    return {"token": token, "user": _user_to_dict(user)}


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    return _user_to_dict(user)


@router.post("/change-password")
async def change_password(
    body: ChangePasswordBody,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    if not verify_password(body.old_password, user.hashed_password):
        raise UnauthorizedException("Current password is incorrect")

    new_pw = body.new_password.strip()
    if len(new_pw) < 6:
        raise InvalidUsageException("New password must be at least 6 characters")

    # Reload within this session to attach user to it
    db_user = db.get(UserInDb, user.id)
    if db_user is None:
        raise UnauthorizedException("User not found")
    db_user.hashed_password = hash_password(new_pw)
    return {"ok": True}
