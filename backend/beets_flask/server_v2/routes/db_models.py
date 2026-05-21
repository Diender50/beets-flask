"""DB model CRUD routes — migrated from server/routes/db_models/."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body
from sqlalchemy import select

from beets_flask import invoker
from beets_flask.database import db_session_factory
from beets_flask.database.models.states import (
    CandidateStateInDb,
    FolderInDb,
    SessionStateInDb,
    TaskStateInDb,
)
from beets_flask.server.exceptions import InvalidUsageException, NotFoundException
from beets_flask.server.routes.db_models.base import (
    _cursor_from_string,
    _cursor_to_string,
    _get_n_with_cursor,
)
from beets_flask.server.routes.db_models.session import (
    _get_folder_status_from_db,
    _get_folder_status_from_queues,
)
from beets_flask.server.utility import pop_extra_meta, pop_folder_params, pop_query_param
from beets_flask.server.websocket.status import FolderStatusUpdate, JobStatusUpdate

router = APIRouter(tags=["db-models"])


# ─────────────────────────────────────────────────────────────────
# Generic CRUD factory
# ─────────────────────────────────────────────────────────────────

def _crud_router(model, prefix: str) -> APIRouter:
    r = APIRouter(prefix=prefix)

    @r.get("/")
    async def get_all(cursor: str | None = None, n_items: int = 50) -> dict:
        items, next_cursor = _get_n_with_cursor(model, _cursor_from_string(cursor), n_items)
        cursor_str = _cursor_to_string(next_cursor)
        return {
            "items": items,
            "next": f"{prefix}/?cursor={cursor_str}&n_items={n_items}" if cursor_str else None,
        }

    @r.get("/id/{id}")
    async def get_by_id(id: str) -> dict:
        with db_session_factory() as session:
            item = model.get_by(model.id == id, session=session)
            if not item:
                raise InvalidUsageException(f"Item with id {id} not found", status_code=404)
            return item.to_dict()

    @r.delete("/id/{id}")
    async def delete_by_id(id: str) -> dict:
        with db_session_factory() as session:
            item = model.get_by(model.id == id, session=session)
            if not item:
                return {"message": f"Item with id {id} not found"}
            session.delete(item)
            session.commit()
        return {"message": f"Item with id {id} deleted successfully"}

    return r


# ─────────────────────────────────────────────────────────────────
# Session (extends generic CRUD)
# ─────────────────────────────────────────────────────────────────

session_router = _crud_router(SessionStateInDb, "/session")


@session_router.post("/by_folder")
async def session_by_folder(params: dict[str, Any] = Body(default_factory=dict)) -> dict:
    folder_hashes, folder_paths = pop_folder_params(params, allow_mismatch=True)
    if len(folder_hashes) != 1 and len(folder_paths) != 1:
        raise InvalidUsageException("Provide one folder hash OR one folder path", status_code=400)

    with db_session_factory() as db_session:
        item = SessionStateInDb.get_by_hash_and_path(
            hash=folder_hashes[0],
            path=folder_paths[0],
            db_session=db_session,
        )
        if not item:
            raise NotFoundException(
                f"Item with {folder_hashes=} {folder_paths=} not found",
                status_code=200,
            )
        return item.to_dict()


@session_router.post("/enqueue")
async def session_enqueue(params: dict[str, Any] = Body(default_factory=dict)) -> dict:
    folder_hashes, folder_paths = pop_folder_params(params)
    kind = pop_query_param(params, "kind", str)
    if not isinstance(kind, str):
        raise InvalidUsageException("kind must be one of " + str(invoker.EnqueueKind.__members__))

    extra_meta = pop_extra_meta(params, n_jobs=len(folder_hashes))
    jobs = []
    for hash, path, meta in zip(folder_hashes, folder_paths, extra_meta):
        jobs.append(
            await invoker.enqueue(
                hash, str(path), invoker.EnqueueKind.from_str(kind), extra_meta=meta, **params
            )
        )

    return JobStatusUpdate(
        message=f"{len(jobs)} added as kind: {kind}",
        num_jobs=len(jobs),
        job_metas=[j.get_meta() for j in jobs],
    )


@session_router.post("/add_candidates")
async def session_add_candidates(params: dict[str, Any] = Body(default_factory=dict)) -> dict:
    task_id = pop_query_param(params, "task_id", str)
    session_id = pop_query_param(params, "session_id", str)

    folder_hash: str | None = None
    folder_path: str | None = None

    with db_session_factory() as db_session:
        if session_id is not None:
            s = db_session.execute(
                select(SessionStateInDb).where(SessionStateInDb.id == session_id)
            ).scalar_one_or_none()
            if s is None:
                raise InvalidUsageException(f"Session with session_id {session_id} not found")
            folder_path = s.folder.full_path
            folder_hash = s.folder.hash

        if task_id is not None:
            t = db_session.execute(
                select(TaskStateInDb).where(TaskStateInDb.id == task_id)
            ).scalar_one_or_none()
            if t is None:
                raise InvalidUsageException(f"Task with task_id {task_id} not found")
            folder_path = t.session.folder.full_path
            folder_hash = t.session.folder.hash

    if folder_hash is None or folder_path is None:
        raise InvalidUsageException("task_id or session_id must be provided")

    extra_meta = pop_extra_meta(params, n_jobs=1)
    job = await invoker.enqueue(
        folder_hash,
        folder_path,
        invoker.EnqueueKind.PREVIEW_ADD_CANDIDATES,
        extra_meta=extra_meta[0],
        **params,
    )
    return JobStatusUpdate(
        message=f"searching_candidates for {folder_path}",
        num_jobs=1,
        job_metas=[job.get_meta()],
    )


@session_router.get("/status")
async def session_status(params: dict[str, Any] = Body(default_factory=dict)) -> list:
    from datetime import timedelta

    folder_hashes, folder_paths = pop_folder_params(params)

    if len(folder_hashes) == 0:
        with db_session_factory() as session:
            folders = session.execute(
                select(FolderInDb).order_by(FolderInDb.created_at.desc())
            ).scalars().all()
            folder_hashes = [f.hash for f in folders]
            folder_paths = [f.full_path for f in folders]

    from beets_flask.importer.progress import FolderStatus

    stats: list[FolderStatusUpdate] = []
    for hash, path in zip(folder_hashes, folder_paths):
        db_status, db_date, db_exc = _get_folder_status_from_db(hash)
        job_status, job_date, job_exc = _get_folder_status_from_queues(hash)

        if db_date is not None:
            db_date = db_date.replace(tzinfo=None)
        if job_date is not None:
            job_date = job_date.replace(tzinfo=None)

        status = FolderStatus.UNKNOWN
        exc = None
        if db_date is None and job_date is None:
            pass
        elif (db_date or datetime.min) + timedelta(seconds=1) >= (job_date or datetime.min):
            status = db_status
            exc = db_exc
        else:
            status = job_status
            exc = job_exc

        stats.append(FolderStatusUpdate(path=str(path), hash=hash, status=status, exc=exc))

    return stats


# ─────────────────────────────────────────────────────────────────
# Folder (extends generic CRUD)
# ─────────────────────────────────────────────────────────────────

folder_router = _crud_router(FolderInDb, "/dbfolder")


@folder_router.get("/by_task/{gui_id}")
async def folder_by_taskid(gui_id: str) -> dict:
    with db_session_factory() as db_session:
        folder = db_session.execute(
            select(FolderInDb)
            .join(SessionStateInDb, TaskStateInDb.session_id == SessionStateInDb.id)
            .join(TaskStateInDb, FolderInDb.id == SessionStateInDb.folder_hash)
            .where(TaskStateInDb.id == gui_id)
        ).scalars().first()

        if folder is None:
            raise NotFoundException("Folder not found")
        return folder.to_dict()


# ─────────────────────────────────────────────────────────────────
# Task + Candidate (generic only)
# ─────────────────────────────────────────────────────────────────

task_router = _crud_router(TaskStateInDb, "/task")
candidate_router = _crud_router(CandidateStateInDb, "/candidate")
