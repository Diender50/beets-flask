import os
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from sqlalchemy import func, select
from typing_extensions import TypedDict

from beets_flask.database import db_session_factory
from beets_flask.database.models.states import FolderInDb, SessionStateInDb
from beets_flask.disk import Archive, Folder, dir_files, dir_size, fs_item_from_path, path_to_folder
from beets_flask.importer.progress import Progress
from beets_flask.logger import log
from beets_flask.server.exceptions import InvalidUsageException, NotFoundException
from beets_flask.server.utility import pop_folder_params
from beets_flask.server.websocket.status import trigger_clear_cache
from beets_flask.watchdog.inbox import get_inbox_folders, get_inbox_for_path

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("/tree")
async def get_tree() -> list:
    inbox_folders = get_inbox_folders()
    return [path_to_folder(f, subdirs=False) for f in inbox_folders]


@router.post("/folder")
async def get_folder(params: dict[str, Any] = Body(default_factory=dict)) -> dict:
    folder_hashes, folder_paths = pop_folder_params(params, allow_mismatch=True)

    if len(folder_paths) != 1 and len(folder_hashes) != 1:
        raise InvalidUsageException(
            f"Only one folder path or hash must be provided. Got: {folder_hashes=}, {folder_paths=}"
        )

    folder_path = folder_paths[0] if len(folder_paths) == 1 else None
    folder_hash = folder_hashes[0] if len(folder_hashes) == 1 else None

    if folder_path is not None and not Path(folder_path).is_absolute():
        raise InvalidUsageException(f"Only absolute paths are allowed. Got: {folder_path=}")

    folder: Folder | Archive | None = None

    if folder_hash is not None:
        for inbox_folder in get_inbox_folders():
            for f in path_to_folder(inbox_folder, subdirs=False).walk():
                if isinstance(f, (Folder, Archive)) and f.hash == folder_hash:
                    folder = f
                    break
            if folder is not None:
                break

        if folder is None:
            with db_session_factory() as session:
                f_in_db = session.execute(
                    select(FolderInDb).where(FolderInDb.id == folder_hash)
                ).scalars().first()
                if f_in_db is not None:
                    folder = f_in_db.to_live_folder()

    if folder is None and folder_path is not None:
        try:
            resolved = Path(folder_path).resolve()
            _folder = fs_item_from_path(resolved, subdirs=False)
            assert isinstance(_folder, (Folder, Archive))
            folder = _folder
        except FileNotFoundError:
            with db_session_factory() as session:
                f_in_db = session.execute(
                    select(FolderInDb)
                    .where(FolderInDb.full_path == str(folder_path))
                    .order_by(FolderInDb.updated_at.desc())
                ).scalars().first()
                if f_in_db is not None:
                    folder = f_in_db.to_live_folder()

    if folder is None:
        raise InvalidUsageException(
            f"Could not find folder with {folder_hash=} or path {folder_path=}.",
            status_code=404,
        )

    return folder


@router.post("/tree/refresh")
async def refresh_cache() -> str:
    await trigger_clear_cache()
    return "Ok"


@router.delete("/delete")
async def delete(params: dict[str, Any] = Body(default_factory=dict)) -> dict:
    from cachetools import Cache

    folder_hashes, folder_paths = pop_folder_params(params, allow_empty=False)
    log.debug(f"Deleting folders: {folder_paths=}, {folder_hashes=}")

    seen: set[tuple[Path, str]] = set()
    folder_paths_and_hashes = []
    for path, hash in zip(folder_paths, folder_hashes):
        if (path, hash) not in seen:
            seen.add((path, hash))
            folder_paths_and_hashes.append((path, hash))

    folder_paths_and_hashes = sorted(
        folder_paths_and_hashes, key=lambda x: len(x[0].parts), reverse=True
    )

    cache: Cache[str, bytes] = Cache(maxsize=2**16)
    folders: list[Folder | Archive] = []
    for folder_path, folder_hash in folder_paths_and_hashes:
        f = fs_item_from_path(folder_path, cache=cache)
        if not isinstance(f, (Folder, Archive)):
            log.debug(f"Skipping deletion of {folder_path}, not a folder or archive")
            continue
        folders.append(f)
        if f.hash != folder_hash:
            raise InvalidUsageException(
                "Folder hash does not match current folder hash! Refresh hashes before deleting!"
            )

    for f in folders:
        if isinstance(f, Archive):
            os.remove(f.full_path)
        elif isinstance(f, Folder):
            shutil.rmtree(f.full_path)
        else:
            raise InvalidUsageException(f"Cannot delete object of type {type(f)} at {f.full_path}")

    await trigger_clear_cache()
    return {"deleted": [f.full_path for f in folders], "hashes": [f.hash for f in folders]}


class InboxStats(TypedDict):
    name: str
    path: str
    tagged_via_gui: int
    imported_via_gui: int
    size: int
    nFiles: int
    last_created: Any


@router.get("/stats")
async def stats_for_all() -> list:
    return [_compute_stats(f) for f in get_inbox_folders()]


def _compute_stats(folder: str) -> InboxStats:
    inbox = get_inbox_for_path(folder)
    if inbox is None:
        raise NotFoundException(f"Inbox folder `{folder}` not found.")

    p = Path(folder)
    with db_session_factory() as session:
        n_tagged = session.execute(
            select(func.count())
            .select_from(SessionStateInDb)
            .join(FolderInDb)
            .where(FolderInDb.full_path.like(f"{folder}%"))
            .where(SessionStateInDb.progress >= Progress.PREVIEW_COMPLETED)
        ).scalar_one()

        n_imported = session.execute(
            select(func.count())
            .select_from(SessionStateInDb)
            .join(FolderInDb)
            .where(FolderInDb.full_path.like(f"{folder}%"))
            .where(SessionStateInDb.progress == Progress.IMPORT_COMPLETED)
        ).scalar_one()

        last_created = session.execute(
            select(SessionStateInDb.created_at)
            .join(FolderInDb)
            .where(FolderInDb.full_path.like(f"{folder}%"))
            .order_by(SessionStateInDb.created_at.desc())
            .limit(1)
        ).scalars().first()

    return {
        "name": inbox["name"],
        "path": inbox["path"],
        "nFiles": dir_files(p),
        "size": dir_size(p),
        "tagged_via_gui": n_tagged,
        "imported_via_gui": n_imported,
        "last_created": last_created,
    }
