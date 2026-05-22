"""Monitor routes — migrated from server/routes/monitor.py."""

from __future__ import annotations

from fastapi import APIRouter
from rq.job import Job
from rq.worker import Worker

from beets_flask.redis import queues, redis_conn

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/queues")
async def get_queue_status() -> dict:
    ret: dict = {}
    for q in queues:
        ret[q.name] = {
            "name": q.name,
            "queued": q.count,
            "queued_jobs": q.job_ids,
            "scheduled": q.scheduled_job_registry.count,
            "executing": q.started_job_registry.count,
            "finished": q.finished_job_registry.count,
            "failed": q.failed_job_registry.count,
        }
    return {"queues": ret}


@router.get("/workers")
async def get_worker_status() -> dict:
    workers = Worker.all(connection=redis_conn)
    ret: dict = {}
    for w in workers:
        ret[w.name] = {
            "name": w.name,
            "queues": w.queue_names(),
            "state": w.get_state(),
            "executed": w.successful_job_count,
            "failed": w.failed_job_count,
        }
    return {"workers": ret}


@router.get("/jobs")
async def get_job_status() -> list:
    ret = []
    for q in queues:
        jobs = Job.fetch_many(q.started_job_registry.get_job_ids(), connection=redis_conn)
        for j in jobs:
            if j is None:
                continue
            ret.append({"q_name": q.name, "job_id": j.id, "meta": j.get_meta(False)})
    return ret


@router.get("/debugResetDb")
async def reset_database() -> dict:
    from beets_flask.database.setup import _reset_database

    _reset_database()
    return {"status": "success"}
