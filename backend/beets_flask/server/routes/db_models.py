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
from collections.abc import Sequence
from typing import TypeVar

from rq.job import Job

from beets_flask.database.models.base import Base
from beets_flask.database.models.states import FolderInDb as _FolderInDb
from beets_flask.importer.progress import FolderStatus, Progress
from beets_flask.logger import log
from beets_flask.server.exceptions import (
    InvalidUsageException,
    NotFoundException,
    SerializedException,
)
from beets_flask.server.utility import pop_extra_meta, pop_folder_params, pop_query_param

_T = TypeVar("_T", bound=Base)


# ── Cursor helpers (inlined from server/routes/db_models/base.py) ─────────────

def _cursor_to_string(cursor: tuple[datetime, str] | None) -> str | None:
    if cursor is None:
        return None
    return f"{cursor[0].isoformat()},{cursor[1]}".encode().hex()


def _cursor_from_string(cursor: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    cursor = bytes.fromhex(cursor).decode("utf-8")
    c = cursor.split(",")
    if len(c) != 2:
        return None
    return datetime.fromisoformat(c[0]), c[1]


def _get_n_with_cursor(model: type[_T], cursor: tuple[datetime, str] | None = None, n_items: int = 50):
    with db_session_factory() as db_session:
        query = select(model)
        if cursor:
            query = query.where((model.created_at <= cursor[0]).__and__(model.id < cursor[1]))
        query = query.order_by(model.created_at.desc(), model.id.desc()).limit(n_items)
        items: Sequence[_T] = db_session.execute(query).scalars().all()
        items_list = [item.to_dict() for item in items]
    next_cursor = (items[-1].created_at, items[-1].id) if len(items) == n_items else None
    return items_list, next_cursor


# ── Status helpers (inlined from server/routes/db_models/session.py) ──────────

def _get_folder_status_from_db(hash: str) -> tuple[FolderStatus, datetime | None, SerializedException | None]:
    with db_session_factory() as db_session:
        s_state_indb = db_session.execute(
            select(SessionStateInDb)
            .where(SessionStateInDb.folder_hash == hash)
            .order_by(SessionStateInDb.folder_revision.desc())
        ).scalars().first()
        if s_state_indb is None:
            return FolderStatus.UNKNOWN, None, None
        status = FolderStatus.UNKNOWN
        if s_state_indb.progress == Progress.NOT_STARTED:
            status = FolderStatus.NOT_STARTED
        elif s_state_indb.progress == Progress.DELETING:
            status = FolderStatus.DELETING
        elif s_state_indb.progress == Progress.DELETION_COMPLETED:
            status = FolderStatus.DELETED
        elif s_state_indb.progress == Progress.PREVIEW_COMPLETED:
            status = FolderStatus.PREVIEWED
        elif s_state_indb.progress == Progress.IMPORT_COMPLETED:
            status = FolderStatus.IMPORTED
        elif s_state_indb.progress < Progress.PREVIEW_COMPLETED:
            status = FolderStatus.PREVIEWING
        elif s_state_indb.progress < Progress.IMPORT_COMPLETED:
            status = FolderStatus.IMPORTING
        exc = s_state_indb.exception if s_state_indb.exception is not None else None
        if exc is not None:
            status = FolderStatus.FAILED
        return status, s_state_indb.updated_at, exc


def _get_folder_status_from_queues(hash: str) -> tuple[FolderStatus, datetime | None, SerializedException | None]:
    from beets_flask.redis import queues, redis_conn

    q_kinds: dict[str, list[Job]] = {"queued": [], "scheduled": [], "started": [], "failed": [], "finished": []}
    for q in queues:
        q_kinds["queued"].extend(_get_jobs(q, redis_conn))
        q_kinds["scheduled"].extend(_get_jobs(q.scheduled_job_registry, redis_conn))
        q_kinds["started"].extend(_get_jobs(q.started_job_registry, redis_conn))
        q_kinds["failed"].extend(_get_jobs(q.failed_job_registry, redis_conn))
        q_kinds["finished"].extend(_get_jobs(q.finished_job_registry, redis_conn))

    job_date = None
    status = FolderStatus.UNKNOWN
    exc = None
    for kind, jobs in q_kinds.items():
        hit = _is_hash_in_jobs(hash, jobs)
        if hit is None:
            continue
        meta, job, _job_date = hit
        if job_date is not None and _job_date <= job_date:
            continue
        job_date = _job_date
        if kind in ("queued", "scheduled"):
            status = FolderStatus.PENDING
        elif kind == "failed":
            status = FolderStatus.FAILED
        elif kind == "started":
            status = FolderStatus.IMPORTING if "import" in meta["job_kind"] else FolderStatus.PREVIEWING
        elif kind == "finished":
            status = FolderStatus.IMPORTED if "import" in meta["job_kind"] else FolderStatus.PREVIEWED
        res = job.latest_result()
        if res and res.return_value and isinstance(res.return_value, dict) and "type" in res.return_value:
            exc = SerializedException(
                type=res.return_value["type"],
                message=res.return_value["message"],
                description=res.return_value.get("description"),
                trace=res.return_value.get("trace"),
            )
            status = FolderStatus.FAILED
        else:
            exc = None
    return status, job_date, exc


def _get_jobs(registry, connection):
    return [j for j in Job.fetch_many(registry.get_job_ids(), connection=connection) if j is not None]


def _is_hash_in_jobs(hash: str, jobs: list[Job]) -> tuple[dict, Job, datetime] | None:
    for j in jobs:
        meta = j.get_meta(False)
        if meta.get("folder_hash") == hash:
            job_dates = [d for d in [j.enqueued_at, j.started_at, j.created_at, j.ended_at] if d]
            return meta, j, max(job_dates)
    return None


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

    return {
        "message": f"{len(jobs)} added as kind: {kind}",
        "num_jobs": len(jobs),
        "job_metas": [j.get_meta() for j in jobs],
        "exc": None,
        "event": "job_status_update",
    }


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
    return {
        "message": f"searching_candidates for {folder_path}",
        "num_jobs": 1,
        "job_metas": [job.get_meta()],
        "exc": None,
        "event": "job_status_update",
    }


@session_router.get("/status")
async def session_status() -> list:
    from datetime import timedelta

    # Return status for all folders (frontend always calls this as a plain GET)
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
