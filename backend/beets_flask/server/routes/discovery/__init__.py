"""Discovery routes: followed artists + album acquisition stubs."""

from __future__ import annotations

import asyncio
import unicodedata
from urllib.parse import quote

import aiohttp
from quart import Blueprint, jsonify, request

from beets_flask.config import get_config
from beets_flask.discovery.download import (
    create_download_job,
    delete_download_job,
    get_all_download_jobs,
    get_download_job,
    run_auto_download,
    run_deemix_download,
    run_slskd_download,
    run_squidwtf_download,
)
from beets_flask.discovery.providers import deemix as deemix_provider
from beets_flask.discovery.providers import slskd as slskd_provider
from beets_flask.discovery.providers import squidwtf as squidwtf_provider
from beets_flask.discovery.followed_artists import (
    follow_artist,
    get_followed_artists,
    is_followed,
    unfollow_artist,
)
from beets_flask.logger import log

discovery_bp = Blueprint("discovery", __name__, url_prefix="/discovery")


@discovery_bp.after_request
async def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


@discovery_bp.route("/<path:path>", methods=["OPTIONS"])
async def handle_options(path: str):
    return "", 200


@discovery_bp.route("", methods=["OPTIONS"])
async def handle_root_options():
    return "", 200


def _all_inbox_paths() -> dict[str, str]:
    try:
        config = get_config()
        folders = config["gui"]["inbox"]["folders"].get({})
    except Exception as exc:
        log.warning("Could not read inbox folders from config: %s", exc)
        return {}

    result: dict[str, str] = {}
    if not isinstance(folders, dict):
        return result

    for folder_key, folder_cfg in folders.items():
        if not isinstance(folder_cfg, dict):
            continue
        path = str(folder_cfg.get("path") or "").strip()
        if not path:
            continue

        result[str(folder_key)] = path

        name = str(folder_cfg.get("name") or "").strip()
        if name:
            result[name] = path

        # Allow selecting direct path as selector value.
        result[path] = path
    return result


def _provider_download_path(provider: str) -> str:
    # `inbox_folder` can be inbox key (Inbox1), inbox name, or direct path.
    selector = _cfg_str(["gui", "discovery", provider, "inbox_folder"], "").strip()
    inbox_paths = _all_inbox_paths()

    if selector and selector in inbox_paths:
        return inbox_paths[selector]

    if selector:
        log.warning(
            "Configured discovery.%s.inbox_folder=%s not found; using fallback inbox path",
            provider,
            selector,
        )

    # Fallback: first configured inbox path.
    if inbox_paths:
        return next(iter(inbox_paths.values()))

    return "/music/inbox_preview"


def _cfg_str(key_path: list, default: str = "") -> str:
    import os
    # Try to read from env var directly (higher priority than yaml)
    env_key = "IB_" + "__".join(k.upper() for k in key_path)
    env_val = os.getenv(env_key)
    if env_val:
        return env_val.strip()
    
    # Fall back to confuse config
    try:
        node = get_config()
        for k in key_path:
            node = node[k]
        val = str(node.get(default)).strip()
        return val if val else default
    except Exception:
        return default


def _cfg_int(key_path: list, default: int) -> int:
    import os
    # Try to read from env var directly (higher priority than yaml)
    env_key = "IB_" + "__".join(k.upper() for k in key_path)
    env_val = os.getenv(env_key)
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    
    # Fall back to confuse config
    try:
        node = get_config()
        for k in key_path:
            node = node[k]
        return int(node.get(default))
    except Exception:
        return default


def _deemix_settings() -> dict:
    base = ["gui", "discovery", "deemix"]
    return {
        "base_url": _cfg_str(base + ["base_url"]),
        "timeout_seconds": _cfg_int(base + ["timeout_seconds"], 20),
        "auth_header": _cfg_str(base + ["auth_header"]) or None,
        "arl": _cfg_str(base + ["arl"]) or None,
    }


def _slskd_settings() -> dict:
    base = ["gui", "discovery", "slskd"]
    rank = ["gui", "discovery", "ranking"]
    return {
        "base_url": _cfg_str(base + ["base_url"]),
        "api_key": _cfg_str(base + ["api_key"]) or None,
        "timeout_seconds": _cfg_int(base + ["timeout_seconds"], 40),
        "ranking_mode": _cfg_str(rank + ["mode"], "balanced").casefold() or "balanced",
        "min_bitrate_kbps": _cfg_int(rank + ["min_bitrate_kbps"], 192),
    }


def _squidwtf_settings() -> dict:
    base = ["gui", "discovery", "squidwtf"]
    return {
        "base_url": _cfg_str(base + ["base_url"], "https://qobuz.squid.wtf"),
        "timeout_seconds": _cfg_int(base + ["timeout_seconds"], 45),
        "quality": _cfg_str(base + ["quality"], "27") or "27",
    }


def _download_suggestion_summary(*, provider: str, score: float, title: str, artist: str, details: dict) -> dict:
    return {
        "provider": provider,
        "score": score,
        "title": title,
        "artist": artist,
        "details": details,
    }


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


@discovery_bp.route("/search/artists", methods=["GET"])
async def search_artists():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q is required"}), 400

    url = f"https://musicbrainz.org/ws/2/artist?query={quote(q)}&limit=15&fmt=json"
    headers = {"User-Agent": "beets-flask/1.0 ( https://github.com/pSpitzner/beets-flask )"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json(content_type=None)
    except Exception as exc:
        log.warning("MusicBrainz artist search failed: %s", exc)
        return jsonify({"error": "MusicBrainz search failed"}), 502

    artists = [
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
    return jsonify(artists)


@discovery_bp.route("/artists", methods=["GET"])
async def list_followed_artists():
    return jsonify(get_followed_artists())


@discovery_bp.route("/artists", methods=["POST"])
async def add_followed_artist():
    data = await request.get_json()
    if not data or not str(data.get("name", "")).strip():
        return jsonify({"error": "name is required"}), 400
    name = str(data["name"]).strip()
    meta = follow_artist(name)
    return jsonify(meta), 201


@discovery_bp.route("/artists/<path:name>", methods=["DELETE"])
async def remove_followed_artist(name: str):
    unfollow_artist(name)
    return jsonify({"ok": True})


@discovery_bp.route("/artists/<path:name>/status", methods=["GET"])
async def followed_artist_status(name: str):
    return jsonify({"name": name, "followed": is_followed(name)})


@discovery_bp.route("/download", methods=["POST"])
async def start_download():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

    provider = str(data.get("provider", "deemix")).strip().casefold()
    album = str(data.get("album", ""))
    artist = str(data.get("artist", ""))
    release_id = str(data.get("release_id", "")).strip() or None
    output_path = _provider_download_path(provider)

    log.info(
        "Download request provider=%s artist=%s album=%s release_id=%s output=%s",
        provider, artist, album, release_id, output_path,
    )

    if provider == "deemix":
        deezer_id = str(data.get("deezer_id", "")).strip() or None
        dcfg = _deemix_settings()

        if not deezer_id:
            if not (artist.strip() or album.strip()):
                return jsonify({"error": "deezer_id or (artist+album) is required"}), 400
            deezer_id = await deemix_provider.resolve_deezer_id_for_album(
                artist=artist,
                album=album,
                timeout_seconds=dcfg["timeout_seconds"],
            )
            if not deezer_id:
                return jsonify({"error": "Could not resolve Deezer release for deemix download"}), 404

        job = create_download_job(
            provider="deemix",
            deezer_id=deezer_id,
            album=album,
            artist=artist,
            release_id=release_id,
        )

        asyncio.ensure_future(
            run_deemix_download(
                job_id=job["job_id"],
                deezer_id=deezer_id,
                output_path=output_path,
                base_url=dcfg["base_url"],
                timeout_seconds=dcfg["timeout_seconds"],
                auth_header=dcfg["auth_header"],
                arl=dcfg["arl"],
            )
        )
        return jsonify(job), 202

    if provider == "slskd":
        if not album.strip() and not artist.strip():
            return jsonify({"error": "artist or album required"}), 400

        scfg = _slskd_settings()
        selected_candidate = data.get("candidate")
        job = create_download_job(
            provider="slskd",
            album=album,
            artist=artist,
            release_id=release_id,
        )

        asyncio.ensure_future(
            run_slskd_download(
                job_id=job["job_id"],
                artist=artist,
                album=album,
                output_path=output_path,
                base_url=scfg["base_url"],
                api_key=scfg["api_key"],
                timeout_seconds=scfg["timeout_seconds"],
                ranking_mode=scfg["ranking_mode"],
                min_bitrate_kbps=scfg["min_bitrate_kbps"],
                selected_candidate=selected_candidate if isinstance(selected_candidate, dict) else None,
            )
        )
        return jsonify(job), 202

    if provider == "squidwtf":
        if not album.strip() and not artist.strip():
            return jsonify({"error": "artist or album required"}), 400

        wcfg = _squidwtf_settings()
        squid_album_id = str(data.get("squid_album_id", "")).strip() or None
        if not squid_album_id:
            match = await squidwtf_provider.resolve_squidwtf_match_for_album(
                artist=artist,
                album=album,
                timeout_seconds=min(20, wcfg["timeout_seconds"]),
                base_url=wcfg["base_url"],
            )
            if not match:
                return jsonify({"error": "Could not resolve SquidWTF release"}), 404
            squid_album_id = str(match.get("squid_album_id") or "").strip() or None
            if not squid_album_id:
                return jsonify({"error": "SquidWTF album id missing in match"}), 502

        job = create_download_job(
            provider="squidwtf",
            squid_album_id=squid_album_id,
            album=album,
            artist=artist,
            release_id=release_id,
        )

        asyncio.ensure_future(
            run_squidwtf_download(
                job_id=job["job_id"],
                artist=artist,
                album=album,
                squid_album_id=squid_album_id,
                output_path=output_path,
                base_url=wcfg["base_url"],
                timeout_seconds=wcfg["timeout_seconds"],
                quality=wcfg["quality"],
            )
        )
        return jsonify(job), 202

    return jsonify({"error": "provider must be 'deemix', 'slskd' or 'squidwtf'"}), 400


@discovery_bp.route("/download/options", methods=["POST"])
async def download_options():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    provider_filter = str(data.get("provider", "")).strip().casefold()
    if not artist and not album:
        return jsonify({"error": "artist or album required"}), 400
    if provider_filter and provider_filter not in ("deemix", "slskd", "squidwtf"):
        return jsonify({"error": "provider must be 'deemix', 'slskd' or 'squidwtf' when set"}), 400

    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    wcfg = _squidwtf_settings()
    async def probe_deemix():
        if not dcfg["base_url"]:
            log.warning("deemix base_url not configured, skipping")
            return []
        log.info("Probing deemix for artist=%s album=%s", artist, album)
        account_quality = await deemix_provider.resolve_quality_from_arl(
            base_url=dcfg["base_url"],
            timeout_seconds=dcfg["timeout_seconds"],
            auth_header=dcfg["auth_header"],
            arl=dcfg["arl"],
        )
        # Deezer search can be sensitive to punctuation/diacritics; try normalized fallback.
        query_attempts = [(artist, album)]
        fallback_artist = _strip_accents(artist)
        fallback_album = _strip_accents(album)
        if (fallback_artist, fallback_album) != (artist, album):
            query_attempts.append((fallback_artist, fallback_album))

        match = None
        for q_artist, q_album in query_attempts:
            try:
                match = await deemix_provider.resolve_deezer_match_for_album(
                    artist=q_artist,
                    album=q_album,
                    timeout_seconds=dcfg["timeout_seconds"],
                )
            except Exception as exc:
                log.warning(
                    "deemix probe failed (artist=%s album=%s): %r",
                    q_artist,
                    q_album,
                    exc,
                )
            if match:
                break

        if not match:
            log.info("deemix: no match found")
            return []
        log.info("deemix: match score=%.2f title=%s", match.get("score", 0), match.get("title"))
        return [
            _download_suggestion_summary(
                provider="deemix",
                score=float(match.get("score") or 0.0),
                title=str(match.get("title") or album),
                artist=str(match.get("artist") or artist),
                details={
                    "deezer_id": match.get("deezer_id"),
                    "trackCount": match.get("track_count"),
                    "container": (
                        (account_quality or {}).get("container")
                        or match.get("container")
                    ),
                    "kbps": (
                        (account_quality or {}).get("kbps")
                        if (account_quality or {}).get("kbps") is not None
                        else match.get("kbps")
                    ),
                    "url": f"https://www.deezer.com/album/{match.get('deezer_id')}",
                },
            )
        ]

    async def probe_slskd():
        if not scfg["base_url"]:
            log.warning("slskd base_url not configured, skipping")
            return []
        log.info("Probing slskd for artist=%s album=%s", artist, album)
        candidates = []
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                candidates = await slskd_provider.search_album(
                    base_url=scfg["base_url"],
                    api_key=scfg["api_key"],
                    artist=artist,
                    album=album,
                    timeout_seconds=scfg["timeout_seconds"],
                )
                break
            except Exception as exc:
                last_exc = exc
                log.warning("slskd probe attempt %d failed: %r", attempt + 1, exc)
                await asyncio.sleep(0.75)
        if not candidates and last_exc is not None:
            raise last_exc

        ranked = slskd_provider.rank_candidates(
            candidates,
            ranking_mode=scfg["ranking_mode"],
            min_bitrate_kbps=scfg["min_bitrate_kbps"],
        )
        log.info("slskd: %d candidates ranked", len(ranked))
        options = []
        for candidate in ranked[:20]:
            score = float(slskd_provider.score_candidate(
                candidate,
                ranking_mode=scfg["ranking_mode"],
                min_bitrate_kbps=scfg["min_bitrate_kbps"],
            ))
            folder = candidate.get("folder", "")
            folder_name = folder.rsplit("/", 1)[-1] if folder else album
            file_count = len(candidate.get("files") or [])
            options.append(
                _download_suggestion_summary(
                    provider="slskd",
                    score=score,
                    title=folder_name or album,
                    artist=artist,
                    details={
                        "searchId": candidate.get("searchId"),
                        "username": candidate.get("username"),
                        "folder": folder,
                        "fileCount": file_count,
                        "audioFileCount": candidate.get("audioFileCount"),
                        "meanAudioBitrateKbps": candidate.get("meanAudioBitrateKbps"),
                        "extension": candidate.get("extension"),
                        "sampleRate": candidate.get("sampleRate"),
                        "bitDepth": candidate.get("bitDepth"),
                        "uploadSpeed": candidate.get("uploadSpeed"),
                        "queueLength": candidate.get("queueLength"),
                        "hasFreeUploadSlot": candidate.get("hasFreeUploadSlot"),
                        "totalSize": candidate.get("totalSize"),
                        "candidate": candidate,
                    },
                )
            )
        return options

    async def probe_squidwtf():
        base_url = wcfg["base_url"]
        if not base_url:
            log.warning("squidwtf base_url not configured, skipping")
            return []
        log.info("Probing squidwtf for artist=%s album=%s", artist, album)

        match = await squidwtf_provider.resolve_squidwtf_match_for_album(
            artist=artist,
            album=album,
            timeout_seconds=min(20, wcfg["timeout_seconds"]),
            base_url=base_url,
        )
        if not match:
            return []

        quality_info = squidwtf_provider.quality_label_to_display(wcfg["quality"])
        return [
            _download_suggestion_summary(
                provider="squidwtf",
                score=float(match.get("score") or 0.0),
                title=str(match.get("title") or album),
                artist=str(match.get("artist") or artist),
                details={
                    "squid_album_id": match.get("squid_album_id"),
                    "trackCount": match.get("track_count"),
                    "quality": wcfg["quality"],
                    "container": quality_info.get("container"),
                    "kbps": quality_info.get("kbps"),
                    "source": "qobuz",
                    "url": f"{base_url.rstrip('/')}/api/get-album?album_id={match.get('squid_album_id')}",
                },
            )
        ]

    deemix_options: list[dict] = []
    slskd_options: list[dict] = []
    squidwtf_options: list[dict] = []

    if provider_filter == "deemix":
        try:
            deemix_options = await probe_deemix()
        except Exception as exc:
            log.warning("probe_deemix failed: %r", exc)
    elif provider_filter == "slskd":
        try:
            slskd_options = await probe_slskd()
        except Exception as exc:
            log.warning("probe_slskd failed: %r", exc)
    elif provider_filter == "squidwtf":
        try:
            squidwtf_options = await probe_squidwtf()
        except Exception as exc:
            log.warning("probe_squidwtf failed: %r", exc)
    else:
        # Run both probes in parallel, but return as soon as slskd is done.
        # deemix and squidwtf are best-effort and must not block slskd results.
        deemix_task = asyncio.create_task(probe_deemix())
        slskd_task = asyncio.create_task(probe_slskd())
        squidwtf_task = asyncio.create_task(probe_squidwtf())

        try:
            slskd_result = await slskd_task
            slskd_options = slskd_result if isinstance(slskd_result, list) else []
        except Exception as exc:
            log.warning("probe_slskd failed: %r", exc)

        # If deemix/squidwtf are ready too, include them; otherwise return immediately with slskd.
        try:
            deemix_result = await asyncio.wait_for(deemix_task, timeout=0.75)
            deemix_options = deemix_result if isinstance(deemix_result, list) else []
        except asyncio.TimeoutError:
            deemix_task.cancel()
            log.info("deemix probe still running when slskd finished; returning partial results")
        except Exception as exc:
            log.warning("probe_deemix failed: %r", exc)

        try:
            squid_result = await asyncio.wait_for(squidwtf_task, timeout=0.75)
            squidwtf_options = squid_result if isinstance(squid_result, list) else []
        except asyncio.TimeoutError:
            squidwtf_task.cancel()
            log.info("squidwtf probe still running when slskd finished; returning partial results")
        except Exception as exc:
            log.warning("probe_squidwtf failed: %r", exc)
    results = [*deemix_options, *slskd_options, *squidwtf_options]
    results.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    log.info(
        "Download options artist=%s album=%s deemix=%d slskd=%d squidwtf=%d",
        artist, album, len(deemix_options), len(slskd_options), len(squidwtf_options),
    )
    return jsonify({
        "artist": artist,
        "album": album,
        "results": results,
    })


@discovery_bp.route("/download/slskd/searches", methods=["DELETE"])
async def slskd_cleanup_searches():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    raw_ids = data.get("search_ids") or []
    if not isinstance(raw_ids, list):
        return jsonify({"error": "search_ids must be a list when provided"}), 400
    search_ids = [str(value).strip() for value in raw_ids if str(value).strip()]

    if not artist and not album and not search_ids:
        return jsonify({"error": "artist+album or search_ids required"}), 400

    scfg = _slskd_settings()
    if not scfg["base_url"]:
        return jsonify({"deleted": 0, "reason": "slskd base_url not configured"}), 200

    deleted = await slskd_provider.delete_searches_for_query(
        base_url=scfg["base_url"],
        api_key=scfg["api_key"],
        artist=artist,
        album=album,
        timeout_seconds=max(8, scfg["timeout_seconds"]),
        search_ids=search_ids,
    )
    return jsonify({"deleted": deleted})


@discovery_bp.route("/download/slskd/search", methods=["POST"])
async def slskd_search():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    if not artist and not album:
        return jsonify({"error": "artist or album required"}), 400

    scfg = _slskd_settings()
    candidates = await slskd_provider.search_album(
        base_url=scfg["base_url"],
        api_key=scfg["api_key"],
        artist=artist,
        album=album,
        timeout_seconds=scfg["timeout_seconds"],
    )
    ranked = slskd_provider.rank_candidates(
        candidates,
        ranking_mode=scfg["ranking_mode"],
        min_bitrate_kbps=scfg["min_bitrate_kbps"],
    )
    return jsonify({"total": len(ranked), "results": ranked[:50]})


@discovery_bp.route("/download/slskd/queue", methods=["POST"])
async def slskd_queue_best():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    if not artist and not album:
        return jsonify({"error": "artist or album required"}), 400

    scfg = _slskd_settings()
    output_path = _get_download_path()

    job = create_download_job(provider="slskd", album=album, artist=artist)
    asyncio.ensure_future(
        run_slskd_download(
            job_id=job["job_id"],
            artist=artist,
            album=album,
            output_path=output_path,
            base_url=scfg["base_url"],
            api_key=scfg["api_key"],
            timeout_seconds=scfg["timeout_seconds"],
            ranking_mode=scfg["ranking_mode"],
            min_bitrate_kbps=scfg["min_bitrate_kbps"],
        )
    )
    return jsonify(job), 202


@discovery_bp.route("/download/<job_id>", methods=["GET"])
async def get_job(job_id: str):
    job = get_download_job(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


@discovery_bp.route("/download", methods=["GET"])
async def list_jobs():
    return jsonify(get_all_download_jobs())


@discovery_bp.route("/download/<job_id>", methods=["DELETE"])
async def remove_job(job_id: str):
    delete_download_job(job_id)
    return jsonify({"ok": True})
