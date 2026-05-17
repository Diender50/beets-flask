"""Download job management for album acquisition via deemix."""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from datetime import datetime, timezone

from beets_flask.logger import log
from beets_flask.redis import redis_conn

DOWNLOAD_KEY_PREFIX = "discovery:download:"
DOWNLOAD_SET_KEY = "discovery:downloads"


class DownloadStatus:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    ERROR = "error"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def create_download_job(deezer_id: str, album: str, artist: str) -> dict:
    """Create a new download job and persist it to Redis."""
    job_id = str(uuid.uuid4())
    job: dict = {
        "job_id": job_id,
        "deezer_id": deezer_id,
        "album": album,
        "artist": artist,
        "status": DownloadStatus.PENDING,
        "error": None,
        "created_at": _now_iso(),
        "completed_at": None,
        "output_path": None,
    }
    redis_conn.hset(
        f"{DOWNLOAD_KEY_PREFIX}{job_id}",
        mapping={k: json.dumps(v) for k, v in job.items()},
    )
    redis_conn.sadd(DOWNLOAD_SET_KEY, job_id)
    return job


def get_download_job(job_id: str) -> dict | None:
    data = redis_conn.hgetall(f"{DOWNLOAD_KEY_PREFIX}{job_id}")
    if not data:
        return None
    return {k.decode(): json.loads(v) for k, v in data.items()}


def get_all_download_jobs() -> list[dict]:
    job_ids = redis_conn.smembers(DOWNLOAD_SET_KEY)
    jobs = []
    for jid in job_ids:
        job = get_download_job(jid.decode())
        if job:
            jobs.append(job)
    return sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)


def delete_download_job(job_id: str) -> bool:
    removed = redis_conn.srem(DOWNLOAD_SET_KEY, job_id)
    redis_conn.delete(f"{DOWNLOAD_KEY_PREFIX}{job_id}")
    return bool(removed)


def _update_job(job_id: str, **fields) -> None:
    updates = {k: json.dumps(v) for k, v in fields.items()}
    redis_conn.hset(f"{DOWNLOAD_KEY_PREFIX}{job_id}", mapping=updates)


async def run_download(job_id: str, deezer_id: str, output_path: str) -> None:
    """Execute the deemix download and update job status."""
    deemix_cmd = shutil.which("deemix")
    if not deemix_cmd:
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error="deemix not found in PATH. Install with: pip install deemix",
            completed_at=_now_iso(),
        )
        log.warning("deemix not found; cannot download album deezer:%s", deezer_id)
        return

    _update_job(job_id, status=DownloadStatus.DOWNLOADING, output_path=output_path)
    log.info("Starting deemix download for deezer album %s -> %s", deezer_id, output_path)

    url = f"https://www.deezer.com/album/{deezer_id}"
    cmd = [deemix_cmd, "-b", "320", url, "-p", output_path]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)

        if proc.returncode == 0:
            _update_job(job_id, status=DownloadStatus.DONE, completed_at=_now_iso())
            log.info("deemix download complete for deezer album %s", deezer_id)
        else:
            error_msg = (stdout.decode(errors="replace")[-1000:] if stdout else "Unknown error")
            _update_job(
                job_id,
                status=DownloadStatus.ERROR,
                error=error_msg,
                completed_at=_now_iso(),
            )
            log.error("deemix download failed for deezer album %s: %s", deezer_id, error_msg)
    except asyncio.TimeoutError:
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error="Download timed out after 10 minutes",
            completed_at=_now_iso(),
        )
    except Exception as exc:
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error=str(exc),
            completed_at=_now_iso(),
        )
        log.exception("Unexpected error during deemix download for %s", deezer_id)
