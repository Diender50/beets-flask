"""Download job management for album acquisition via external providers."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from beets_flask.discovery.providers import deemix, slskd

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


def create_download_job(
    *,
    provider: str,
    album: str,
    artist: str,
    deezer_id: str | None = None,
    release_id: str | None = None,
    query: str | None = None,
) -> dict:
    """Create a new download job and persist it to Redis."""
    job_id = str(uuid.uuid4())
    job: dict = {
        "job_id": job_id,
        "provider": provider,
        "deezer_id": deezer_id,
        "release_id": release_id,
        "query": query,
        "album": album,
        "artist": artist,
        "selected_match": None,
        "provider_candidates": [],
        "selection_reason": None,
        "stage": "queued",
        "progress_message": "Queued download request",
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


def _job_summary(job_id: str, **fields) -> str:
    parts = [f"job={job_id}"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts)


def _deemix_candidate_summary(match: dict | None) -> dict | None:
    if not match:
        return None
    return {
        "provider": "deemix",
        "deezer_id": match.get("deezer_id"),
        "title": match.get("title"),
        "artist": match.get("artist"),
        "score": match.get("score"),
    }


def _slskd_candidate_summary(candidate: dict | None, score: float | None = None) -> dict | None:
    if not candidate:
        return None
    return {
        "provider": "slskd",
        "username": candidate.get("username") or candidate.get("user"),
        "filename": candidate.get("filename") or candidate.get("fileName"),
        "bitrate": candidate.get("bitRate") or candidate.get("bitrate") or candidate.get("kbps"),
        "speed": candidate.get("uploadSpeed") or candidate.get("speed") or candidate.get("averageSpeed"),
        "size": candidate.get("size"),
        "score": score,
    }


async def run_download(job_id: str, deezer_id: str, output_path: str) -> None:
    """Backward-compatible wrapper for old deemix-only call sites."""
    await run_deemix_download(
        job_id=job_id,
        deezer_id=deezer_id,
        output_path=output_path,
        base_url="",
        timeout_seconds=20,
        auth_header=None,
    )


async def run_auto_download(
    *,
    job_id: str,
    artist: str,
    album: str,
    output_path: str,
    deemix_base_url: str,
    deemix_timeout_seconds: int,
    deemix_auth_header: str | None,
    deemix_arl: str | None = None,
    slskd_base_url: str,
    slskd_api_key: str | None,
    slskd_timeout_seconds: int,
    ranking_mode: str,
    min_bitrate_kbps: int,
) -> None:
    query = f"{artist} {album}".strip()
    _update_job(
        job_id,
        status=DownloadStatus.DOWNLOADING,
        output_path=output_path,
        query=query,
        provider="auto",
        stage="probing",
        progress_message="Probing deemix and slskd for best release",
    )
    log.info("Auto download probe start %s", _job_summary(job_id, artist=artist, album=album, output=output_path))

    async def probe_deemix() -> dict:
        if not deemix_base_url:
            return {"provider": "deemix", "ok": False, "reason": "deemix base_url not configured"}
        _update_job(job_id, stage="probing", progress_message="Asking deemix for best match")
        log.info("Auto download probe deemix %s", _job_summary(job_id, base_url=deemix_base_url))
        match = await deemix.resolve_deezer_match_for_album(
            artist=artist,
            album=album,
            timeout_seconds=deemix_timeout_seconds,
        )
        if not match:
            return {"provider": "deemix", "ok": False, "reason": "no Deezer match"}
        return {
            "provider": "deemix",
            "ok": True,
            "score": float(match.get("score") or 0.0),
            "match": match,
        }

    async def probe_slskd() -> dict:
        if not slskd_base_url:
            return {"provider": "slskd", "ok": False, "reason": "slskd base_url not configured"}
        _update_job(job_id, stage="probing", progress_message="Asking slskd for best match")
        log.info("Auto download probe slskd %s", _job_summary(job_id, base_url=slskd_base_url))
        candidates = await slskd.search_album(
            base_url=slskd_base_url,
            api_key=slskd_api_key,
            artist=artist,
            album=album,
            timeout_seconds=slskd_timeout_seconds,
        )
        ranked = slskd.rank_candidates(
            candidates,
            ranking_mode=ranking_mode,
            min_bitrate_kbps=min_bitrate_kbps,
        )
        if not ranked:
            return {"provider": "slskd", "ok": False, "reason": "no slskd match"}
        best = ranked[0]
        return {
            "provider": "slskd",
            "ok": True,
            "score": float(slskd.score_candidate(best, ranking_mode=ranking_mode, min_bitrate_kbps=min_bitrate_kbps)),
            "match": best,
        }

    deemix_probe, slskd_probe = await asyncio.gather(probe_deemix(), probe_slskd())
    _update_job(job_id, provider_candidates=[deemix_probe, slskd_probe])

    candidates: list[dict] = [probe for probe in (deemix_probe, slskd_probe) if probe.get("ok")]
    if not candidates:
        reason = "; ".join(str(probe.get("reason") or "unknown") for probe in (deemix_probe, slskd_probe))
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error=reason,
            stage="failed",
            progress_message="No provider returned a usable release",
            completed_at=_now_iso(),
        )
        log.warning("Auto download probe failed %s reason=%s", _job_summary(job_id), reason)
        return

    candidates.sort(key=lambda probe: (float(probe.get("score") or 0.0), 1 if probe.get("provider") == "deemix" else 0), reverse=True)
    selected = candidates[0]
    selected_provider = str(selected["provider"])
    selected_score = float(selected.get("score") or 0.0)
    selected_match = selected.get("match") or {}
    log.info(
        "Auto download selected %s",
        _job_summary(job_id, provider=selected_provider, score=f"{selected_score:.3f}", reason=selected.get("reason")),
    )

    if selected_provider == "deemix":
        match = selected["match"]
        _update_job(
            job_id,
            provider="deemix",
            deezer_id=match.get("deezer_id"),
            selected_match=_deemix_candidate_summary(match),
            selection_reason=f"score={selected_score:.3f}",
            stage="selected",
            progress_message=f"Selected deemix release {match.get('deezer_id')}",
        )
        await run_deemix_download(
            job_id=job_id,
            deezer_id=str(match["deezer_id"]),
            output_path=output_path,
            base_url=deemix_base_url,
            timeout_seconds=deemix_timeout_seconds,
            auth_header=deemix_auth_header,
            arl=deemix_arl,
        )
        return

    match = selected["match"]
    _update_job(
        job_id,
        provider="slskd",
        selected_match=_slskd_candidate_summary(match, selected_score),
        selection_reason=f"score={selected_score:.3f}",
        stage="selected",
        progress_message="Selected slskd candidate",
    )
    await run_slskd_download(
        job_id=job_id,
        artist=artist,
        album=album,
        output_path=output_path,
        base_url=slskd_base_url,
        api_key=slskd_api_key,
        timeout_seconds=slskd_timeout_seconds,
        ranking_mode=ranking_mode,
        min_bitrate_kbps=min_bitrate_kbps,
    )


async def run_deemix_download(
    *,
    job_id: str,
    deezer_id: str,
    output_path: str,
    base_url: str,
    timeout_seconds: int,
    auth_header: str | None,
    arl: str | None = None,
) -> None:
    _update_job(job_id, status=DownloadStatus.DOWNLOADING, output_path=output_path, stage="queued", progress_message="Waiting to queue deemix download")
    log.info("Deemix download start %s", _job_summary(job_id, deezer_id=deezer_id, output=output_path))

    try:
        ok, info = await deemix.enqueue_download(
            base_url=base_url,
            deezer_id=deezer_id,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
            auth_header=auth_header,
            arl=arl,
        )
        if ok:
            _update_job(job_id, stage="done", progress_message="Deemix accepted download request")
            log.info("Deemix download queued %s", _job_summary(job_id, deezer_id=deezer_id))
            _update_job(job_id, status=DownloadStatus.DONE, completed_at=_now_iso(), error=None)
            return

        log.warning("Deemix download failed %s error=%s", _job_summary(job_id, deezer_id=deezer_id), info)
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error=info or "deemix download failed",
            stage="failed",
            progress_message="Deemix rejected download request",
            completed_at=_now_iso(),
        )
    except Exception as exc:
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error=str(exc),
            completed_at=_now_iso(),
        )
        log.exception("Unexpected error during deemix provider download")


async def run_slskd_download(
    *,
    job_id: str,
    artist: str,
    album: str,
    output_path: str,
    base_url: str,
    api_key: str | None,
    timeout_seconds: int,
    ranking_mode: str,
    min_bitrate_kbps: int,
    selected_candidate: dict | None = None,
) -> None:
    _update_job(job_id, status=DownloadStatus.DOWNLOADING, output_path=output_path, stage="searching", progress_message="Searching slskd for matching release")
    query = f"{artist} {album}".strip()
    _update_job(job_id, query=query)
    log.info("Slskd download start %s", _job_summary(job_id, query=query, output=output_path))

    try:
        if selected_candidate:
            candidates = [selected_candidate]
            ranked = [selected_candidate]
            _update_job(job_id, stage="selected", progress_message="Using chosen slskd candidate")
        else:
            candidates = await slskd.search_album(
                base_url=base_url,
                api_key=api_key,
                artist=artist,
                album=album,
                timeout_seconds=timeout_seconds,
            )
            _update_job(job_id, stage="ranking", progress_message=f"Ranked {len(candidates)} slskd candidates")
            ranked = slskd.rank_candidates(
                candidates,
                ranking_mode=ranking_mode,
                min_bitrate_kbps=min_bitrate_kbps,
            )
        log.info(
            "Slskd candidates ranked %s count=%s",
            _job_summary(job_id, query=query),
            len(ranked),
        )
        if not ranked:
            _update_job(
                job_id,
                status=DownloadStatus.ERROR,
                error="No slskd candidate matched current criteria",
                completed_at=_now_iso(),
                stage="failed",
                progress_message="slskd found nothing usable",
            )
            return

        best = ranked[0]
        best_score = slskd.score_candidate(
            best,
            ranking_mode=ranking_mode,
            min_bitrate_kbps=min_bitrate_kbps,
        )
        _update_job(job_id, selected_match={
            "username": best.get("username") or best.get("user"),
            "filename": best.get("filename") or best.get("fileName"),
            "bitrate": best.get("bitRate") or best.get("bitrate") or best.get("kbps"),
            "speed": best.get("uploadSpeed") or best.get("speed") or best.get("averageSpeed"),
            "size": best.get("size"),
            "score": best_score,
        })
        _update_job(job_id, stage="selected", progress_message="Selected best slskd candidate")
        log.info(
            "Slskd selected candidate %s score=%.3f",
            _job_summary(job_id, query=query),
            best_score,
        )

        ok, info = await slskd.enqueue_download(
            base_url=base_url,
            api_key=api_key,
            candidate=best,
            output_path=output_path,
            timeout_seconds=timeout_seconds,
        )
        if ok:
            _update_job(job_id, stage="done", progress_message="slskd accepted download request")
            log.info("Slskd download queued %s", _job_summary(job_id, query=query))
            _update_job(job_id, status=DownloadStatus.DONE, completed_at=_now_iso(), error=None)
            return

        log.warning("Slskd download failed %s error=%s", _job_summary(job_id, query=query), info)
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error=info or "slskd enqueue failed",
            stage="failed",
            progress_message="slskd rejected download request",
            completed_at=_now_iso(),
        )
    except Exception as exc:
        _update_job(
            job_id,
            status=DownloadStatus.ERROR,
            error=str(exc),
            completed_at=_now_iso(),
        )
        log.exception("Unexpected error during slskd provider download")
