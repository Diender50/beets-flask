"""Discovery routes — migrated from server/routes/discovery/__init__.py."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

# All pure business-logic helpers reused directly — no Quart imports inside them.
from beets_flask.server.routes.discovery import (
    _auto_download_quality_priority,
    _find_best_match_across_providers,
    _musicbrainz_api_base_url,
    _provider_download_path,
    _schedule_download_from_payload,
    _deemix_settings,
    _slskd_settings,
)
from beets_flask.discovery.download import (
    create_download_job,
    delete_download_job,
    get_all_download_jobs,
    get_download_job,
)
from beets_flask.discovery.followed_artists import (
    follow_artist,
    get_followed_artists,
    is_followed,
    unfollow_artist,
)
from beets_flask.library_cache import (
    get_missing_count_map,
    invalidate_missing_cache_for_string,
    normalize_artist_key,
)
from beets_flask.logger import log

router = APIRouter(prefix="/discovery", tags=["discovery"])


# ─── Quality ─────────────────────────────────────────────────────────────────


@router.get("/quality-priority")
async def get_quality_priority() -> dict:
    return {"quality_priority": _auto_download_quality_priority()}


# ─── Artist search / follow ───────────────────────────────────────────────────


@router.get("/search/artists")
async def search_artists(q: str = "") -> list:
    import aiohttp
    from urllib.parse import quote

    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")

    base_url = _musicbrainz_api_base_url()
    url = f"{base_url}/artist?query={quote(q)}&limit=15&fmt=json"
    headers = {"User-Agent": "beets-flask/1.0 ( https://github.com/pSpitzner/beets-flask )"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:
        log.warning("MusicBrainz artist search failed: %s", exc)
        raise HTTPException(status_code=502, detail="MusicBrainz search failed")

    return [
        {
            "id": a.get("id"),
            "name": a.get("name", ""),
            "sort_name": a.get("sort-name", ""),
            "disambiguation": a.get("disambiguation", ""),
            "country": a.get("country", ""),
            "score": a.get("score", 0),
            "followed": bool(is_followed(a.get("name", ""))),
        }
        for a in data.get("artists", [])
    ]


@router.get("/artists")
async def list_followed_artists() -> list:
    artists = get_followed_artists()
    missing_map = get_missing_count_map()
    for a in artists:
        a["missing_count"] = missing_map.get(normalize_artist_key(a["name"]), 0)
    return artists


@router.post("/artists", status_code=201)
async def add_followed_artist(data: dict[str, Any] = Body(default_factory=dict)) -> dict:
    if not data or not str(data.get("name", "")).strip():
        raise HTTPException(status_code=400, detail="name is required")
    name = str(data["name"]).strip()
    return follow_artist(name)


@router.delete("/artists/{name:path}")
async def remove_followed_artist(name: str) -> dict:
    unfollow_artist(name)
    invalidate_missing_cache_for_string(name)
    return {"ok": True}


@router.get("/artists/{name:path}/status")
async def followed_artist_status(name: str) -> dict:
    return {"name": name, "followed": is_followed(name)}


# ─── Downloads ────────────────────────────────────────────────────────────────


@router.post("/download")
async def start_download(data: dict[str, Any] = Body(default_factory=dict)):
    if not data:
        raise HTTPException(status_code=400, detail="request body is required")
    payload, status = await _schedule_download_from_payload(data)
    from fastapi.responses import JSONResponse
    return JSONResponse(content=payload, status_code=status)


@router.post("/download/batch")
async def start_download_batch(data: dict[str, Any] = Body(default_factory=dict)):
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="request body is required")

    providers_raw = data.get("providers", [])
    providers = [str(p).strip().casefold() for p in (providers_raw if isinstance(providers_raw, list) else [])]
    providers = [p for p in providers if p in ("deemix", "slskd", "squidwtf")] or ["deemix", "slskd", "squidwtf"]

    qualities_raw = data.get("qualities") or None
    qualities: list[str] | None = None
    if isinstance(qualities_raw, list) and qualities_raw:
        qualities = [str(q).strip() for q in qualities_raw if str(q).strip()]

    albums = data.get("albums")
    if not isinstance(albums, list) or len(albums) == 0:
        raise HTTPException(status_code=400, detail="albums must be a non-empty list")

    jobs: list[dict] = []
    errors: list[dict] = []
    for idx, album_payload in enumerate(albums):
        if not isinstance(album_payload, dict):
            errors.append({"index": idx, "error": "album payload must be an object"})
            continue

        best = await _find_best_match_across_providers(album_payload=album_payload, providers=providers, qualities=qualities)
        if not best:
            errors.append({
                "index": idx,
                "artist": str(album_payload.get("artist", "")),
                "album": str(album_payload.get("album", "")),
                "error": "No match found across selected providers and qualities",
                "status": 404,
            })
            continue

        job_or_error, status = await _schedule_download_from_payload(best)
        if 200 <= status < 300:
            jobs.append(job_or_error)
        else:
            errors.append({
                "index": idx,
                "artist": str(best.get("artist", "")),
                "album": str(best.get("album", "")),
                "error": str(job_or_error.get("error", "Download scheduling failed")),
                "status": status,
            })

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"providers": providers, "qualities": qualities, "requested": len(albums),
                 "queued": len(jobs), "failed": len(errors), "jobs": jobs, "errors": errors},
        status_code=202 if jobs else 400,
    )


@router.post("/download/options")
async def download_options(data: dict[str, Any] = Body(default_factory=dict)):
    # Re-import here to avoid circular import at module load time
    from beets_flask.server.routes.discovery import (
        _squidwtf_settings,
        _strip_accents,
        _download_suggestion_summary,
    )
    from beets_flask.discovery.providers import deemix as deemix_provider
    from beets_flask.discovery.providers import slskd as slskd_provider
    from beets_flask.discovery.providers import squidwtf as squidwtf_provider
    import asyncio

    if not data:
        raise HTTPException(status_code=400, detail="request body is required")

    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    provider_filter = str(data.get("provider", "")).strip().casefold()
    expected_track_count: int | None = None
    try:
        _etc = data.get("expected_track_count")
        if _etc is not None:
            expected_track_count = int(_etc)
    except (TypeError, ValueError):
        pass

    if not artist and not album:
        raise HTTPException(status_code=400, detail="artist or album required")
    if provider_filter and provider_filter not in ("deemix", "slskd", "squidwtf"):
        raise HTTPException(status_code=400, detail="provider must be 'deemix', 'slskd' or 'squidwtf' when set")

    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    wcfg = _squidwtf_settings()

    # Probe functions defined as closures (same logic as Quart original)
    async def probe_deemix():
        if not dcfg["base_url"]:
            return []
        account_quality = await deemix_provider.resolve_quality_from_arl(
            base_url=dcfg["base_url"], timeout_seconds=dcfg["timeout_seconds"],
            auth_header=dcfg["auth_header"], arl=dcfg["arl"],
        )
        query_attempts = [(artist, album)]
        fa, fb = _strip_accents(artist), _strip_accents(album)
        if (fa, fb) != (artist, album):
            query_attempts.append((fa, fb))

        match = None
        for q_artist, q_album in query_attempts:
            try:
                match = await deemix_provider.resolve_deezer_match_for_album(
                    artist=q_artist, album=q_album, timeout_seconds=dcfg["timeout_seconds"]
                )
            except Exception:
                pass
            if match:
                break

        if not match:
            return []
        return [_download_suggestion_summary(
            provider="deemix", score=float(match.get("score") or 0.0),
            title=str(match.get("title") or album), artist=str(match.get("artist") or artist),
            details={"deezer_id": match.get("deezer_id"), "trackCount": match.get("track_count"),
                     "container": (account_quality or {}).get("container") or match.get("container"),
                     "kbps": (account_quality or {}).get("kbps") if (account_quality or {}).get("kbps") is not None else match.get("kbps"),
                     "url": f"https://www.deezer.com/album/{match.get('deezer_id')}"},
        )]

    async def probe_slskd():
        if not scfg["base_url"]:
            return []
        candidates = await slskd_provider.search_album(
            base_url=scfg["base_url"], api_key=scfg["api_key"],
            artist=artist, album=album, timeout_seconds=scfg["timeout_seconds"],
        )
        ranked = slskd_provider.rank_candidates(candidates, album_hint=album, expected_track_count=expected_track_count)
        return [
            _download_suggestion_summary(
                provider="slskd", score=float(slskd_provider.score_candidate(c, album_hint=album, expected_track_count=expected_track_count)),
                title=(c.get("folder", "").rsplit("/", 1)[-1] or album), artist=artist,
                details={"searchId": c.get("searchId"), "username": c.get("username"),
                         "folder": c.get("folder"), "fileCount": len(c.get("files") or []),
                         "audioFileCount": c.get("audioFileCount"), "meanAudioBitrateKbps": c.get("meanAudioBitrateKbps"),
                         "extension": c.get("extension"), "sampleRate": c.get("sampleRate"),
                         "bitDepth": c.get("bitDepth"), "uploadSpeed": c.get("uploadSpeed"),
                         "queueLength": c.get("queueLength"), "hasFreeUploadSlot": c.get("hasFreeUploadSlot"),
                         "totalSize": c.get("totalSize"), "candidate": c},
            )
            for c in ranked[:20]
        ]

    async def probe_squidwtf():
        if not wcfg["base_url"]:
            return []
        match = await squidwtf_provider.resolve_squidwtf_match_for_album(
            artist=artist, album=album, timeout_seconds=min(20, wcfg["timeout_seconds"]), base_url=wcfg["base_url"],
        )
        if not match:
            return []
        squid_album_id = match.get("squid_album_id")
        results = []
        for q_alias, q_code in [("flac:hires", "27"), ("flac:16", "6"), ("mp3:320", "5")]:
            qi = squidwtf_provider.quality_label_to_display(q_alias)
            results.append(_download_suggestion_summary(
                provider="squidwtf", score=float(match.get("score") or 0.0),
                title=str(match.get("title") or album), artist=str(match.get("artist") or artist),
                details={"squid_album_id": squid_album_id, "trackCount": match.get("track_count"),
                         "quality": q_code, "container": qi.get("container"), "kbps": qi.get("kbps"),
                         "source": "qobuz", "url": f"{wcfg['base_url'].rstrip('/')}/api/get-album?album_id={squid_album_id}"},
            ))
        return results

    deemix_opts = slskd_opts = squidwtf_opts = []
    if provider_filter == "deemix":
        try:
            deemix_opts = await probe_deemix()
        except Exception as exc:
            log.warning("probe_deemix failed: %r", exc)
    elif provider_filter == "slskd":
        try:
            slskd_opts = await probe_slskd()
        except Exception as exc:
            log.warning("probe_slskd failed: %r", exc)
    elif provider_filter == "squidwtf":
        try:
            squidwtf_opts = await probe_squidwtf()
        except Exception as exc:
            log.warning("probe_squidwtf failed: %r", exc)
    else:
        deemix_task = asyncio.create_task(probe_deemix())
        slskd_task = asyncio.create_task(probe_slskd())
        squidwtf_task = asyncio.create_task(probe_squidwtf())
        try:
            slskd_opts = await slskd_task
        except Exception as exc:
            log.warning("probe_slskd failed: %r", exc)
        try:
            deemix_opts = await asyncio.wait_for(deemix_task, timeout=0.75)
        except (asyncio.TimeoutError, Exception) as exc:
            deemix_task.cancel()
        try:
            squidwtf_opts = await asyncio.wait_for(squidwtf_task, timeout=0.75)
        except (asyncio.TimeoutError, Exception) as exc:
            squidwtf_task.cancel()

    results = sorted([*deemix_opts, *slskd_opts, *squidwtf_opts], key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return {"artist": artist, "album": album, "results": results}


@router.delete("/download/slskd/searches")
async def slskd_cleanup_searches(data: dict[str, Any] = Body(default_factory=dict)) -> dict:
    from beets_flask.discovery.providers import slskd as slskd_provider

    if not data:
        raise HTTPException(status_code=400, detail="request body is required")
    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    raw_ids = data.get("search_ids") or []
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="search_ids must be a list when provided")
    search_ids = [str(v).strip() for v in raw_ids if str(v).strip()]
    if not artist and not album and not search_ids:
        raise HTTPException(status_code=400, detail="artist+album or search_ids required")

    scfg = _slskd_settings()
    if not scfg["base_url"]:
        return {"deleted": 0, "reason": "slskd base_url not configured"}

    deleted = await slskd_provider.delete_searches_for_query(
        base_url=scfg["base_url"], api_key=scfg["api_key"],
        artist=artist, album=album,
        timeout_seconds=max(8, scfg["timeout_seconds"]),
        search_ids=search_ids,
    )
    return {"deleted": deleted}


@router.post("/download/slskd/search")
async def slskd_search(data: dict[str, Any] = Body(default_factory=dict)) -> dict:
    from beets_flask.discovery.providers import slskd as slskd_provider

    if not data:
        raise HTTPException(status_code=400, detail="request body is required")
    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    if not artist and not album:
        raise HTTPException(status_code=400, detail="artist or album required")

    scfg = _slskd_settings()
    candidates = await slskd_provider.search_album(
        base_url=scfg["base_url"], api_key=scfg["api_key"],
        artist=artist, album=album, timeout_seconds=scfg["timeout_seconds"],
    )
    ranked = slskd_provider.rank_candidates(candidates, album_hint=album)
    return {"total": len(ranked), "results": ranked[:50]}


@router.post("/download/slskd/queue", status_code=202)
async def slskd_queue_best(data: dict[str, Any] = Body(default_factory=dict)) -> dict:
    import asyncio
    from beets_flask.discovery.download import run_slskd_download

    if not data:
        raise HTTPException(status_code=400, detail="request body is required")
    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    if not artist and not album:
        raise HTTPException(status_code=400, detail="artist or album required")

    scfg = _slskd_settings()
    output_path = _provider_download_path("slskd")
    job = create_download_job(provider="slskd", album=album, artist=artist)
    asyncio.ensure_future(
        run_slskd_download(
            job_id=job["job_id"], artist=artist, album=album,
            output_path=output_path, base_url=scfg["base_url"],
            api_key=scfg["api_key"], timeout_seconds=scfg["timeout_seconds"],
        )
    )
    return job


@router.get("/download/{job_id}")
async def get_job(job_id: str) -> dict:
    job = get_download_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/download")
async def list_jobs() -> list:
    return get_all_download_jobs()


@router.delete("/download/{job_id}")
async def remove_job(job_id: str) -> dict:
    delete_download_job(job_id)
    return {"ok": True}
