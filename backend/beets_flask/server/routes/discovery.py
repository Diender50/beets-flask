"""Discovery routes."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any
from urllib.parse import quote

import aiohttp
from fastapi import APIRouter, Body, HTTPException

from beets_flask.config import get_config
from beets_flask.discovery.download import (
    create_download_job,
    delete_download_job,
    get_all_download_jobs,
    get_download_job,
    run_deemix_download,
    run_slskd_download,
    run_squidwtf_download,
)
from beets_flask.discovery.tracked_artists import (
    add_tracked_artist,
    get_tracked_artists,
    get_tracked_artist,
    is_tracked,
    remove_tracked_artist,
)
from beets_flask.discovery.providers import deemix as deemix_provider
from beets_flask.discovery.providers import slskd as slskd_provider
from beets_flask.discovery.providers import squidwtf as squidwtf_provider
from beets_flask.library_cache import (
    get_missing_count_map,
    invalidate_artists_cache,
    invalidate_missing_cache_for_string,
    normalize_artist_key,
)
from beets_flask.logger import log
from beets_flask.server.dependencies import BeetsLib, CurrentUser
from beets_flask.server.routes.library.resources import delete_entities

# ─── Helpers (inlined from server/routes/discovery) ──────────────────────────


def _all_inbox_paths() -> dict[str, str]:
    try:
        config = get_config()
        folders_view = config["gui"]["inbox"]["folders"]
    except Exception as exc:
        log.warning("Could not read inbox folders from config: %s", exc)
        return {}

    result: dict[str, str] = {}
    try:
        flat_values = folders_view.flatten().values()  # type: ignore[attr-defined]
        for folder_cfg in flat_values:
            if not isinstance(folder_cfg, dict):
                continue
            path = str(folder_cfg.get("path") or "").strip()
            if not path:
                continue

            key = str(folder_cfg.get("__key__") or "").strip()
            if key:
                result[key] = path

            name = str(folder_cfg.get("name") or "").strip()
            if name:
                result[name] = path

            result[path] = path
    except Exception:
        try:
            folders = folders_view.get({})
        except Exception:
            folders = {}

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

            result[path] = path

    try:
        for k in folders_view.keys():
            key = str(k)
            try:
                path = str(folders_view[key]["path"].as_str()).strip()
            except Exception:
                path = ""
            if path:
                result[key] = path
    except Exception:
        pass
    return result


def _provider_download_path(provider: str) -> str:
    selector = _cfg_str(["gui", "discovery", provider, "inbox_folder"], "").strip()
    inbox_paths = _all_inbox_paths()

    if selector and selector in inbox_paths:
        return inbox_paths[selector]

    if selector:
        selector_cf = selector.casefold()
        for key, path in inbox_paths.items():
            if str(key).casefold() == selector_cf:
                return path

    if selector:
        log.warning(
            "Configured discovery.%s.inbox_folder=%s not found; using fallback inbox path (known=%s)",
            provider,
            selector,
            ",".join(sorted(set(inbox_paths.keys()))),
        )

    if inbox_paths:
        return next(iter(inbox_paths.values()))

    return "/music/inbox_preview"


def _cfg_str(key_path: list, default: str = "") -> str:
    import os
    env_key = "IB_" + "__".join(k.upper() for k in key_path)
    env_val = os.getenv(env_key)
    if env_val:
        return env_val.strip()

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
    env_key = "IB_" + "__".join(k.upper() for k in key_path)
    env_val = os.getenv(env_key)
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass

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
    scoring = base + ["scoring"]
    return {
        "base_url": _cfg_str(base + ["base_url"]),
        "api_key": _cfg_str(base + ["api_key"]) or None,
        "timeout_seconds": _cfg_int(base + ["timeout_seconds"], 40),
        "speed_min_bps": _cfg_int(scoring + ["speed_min_bps"], 1_000_000),
        "queue_max": _cfg_int(scoring + ["queue_max"], 100),
    }


def _squidwtf_settings() -> dict:
    base = ["gui", "discovery", "squidwtf"]
    return {
        "base_url": _cfg_str(base + ["base_url"], "https://qobuz.squid.wtf"),
        "timeout_seconds": _cfg_int(base + ["timeout_seconds"], 45),
    }


def _musicbrainz_api_base_url() -> str:
    return _cfg_str(
        ["gui", "discovery", "musicbrainz", "base_url"],
        "https://musicbrainz.org/ws/2",
    ).rstrip("/")


def _download_suggestion_summary(*, provider: str, score: float, title: str, artist: str, details: dict) -> dict:
    return {
        "provider": provider,
        "score": score,
        "title": title,
        "artist": artist,
        "details": details,
    }


_APOSTROPHE_RE = re.compile("['`´ʹʻʼʽ‘’‚‛′‵＇]")


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    no_combining = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return _APOSTROPHE_RE.sub("'", no_combining)


def _artist_known_names_set(
    artist: str,
    original_name: str | None,
    other_aliases: list[str],
) -> set[str]:
    """Normalized set of all known name variants for artist-match validation."""
    names: set[str] = {artist}
    if original_name:
        names.add(original_name)
    names.update(other_aliases)
    return {_strip_accents(n).casefold() for n in names if n}


def _get_artist_search_fallbacks(artist_name: str) -> dict:
    """Return {original_name: str|None, other_aliases: list[str]} for download queries.

    original_name: raw MB name when artist was added under an EN/FR alias (e.g. "大貫妙子")
    other_aliases: non-primary EN/FR aliases from the MB alias cache, excluding artist_name
                   and original_name
    """
    import json as _json

    result: dict = {"original_name": None, "other_aliases": []}
    try:
        from beets_flask.database.models.users import TrackedArtistInDb
        from beets_flask.database.setup import session_factory
        from beets_flask.library_cache import get_json_cache

        session = session_factory()
        try:
            row = (
                session.query(TrackedArtistInDb)
                .filter(TrackedArtistInDb.artist_name == artist_name)
                .first()
            )
            if row and row.original_name and row.original_name != artist_name:
                result["original_name"] = row.original_name
        finally:
            session.close()

        name_cached = get_json_cache(f"mb_artist_name:{artist_name.casefold()}")
        if name_cached:
            mbid = _json.loads(name_cached).get("mbid")
            if mbid:
                aliases_cached = get_json_cache(f"mb_aliases_all:{mbid}")
                if aliases_cached:
                    skip = {artist_name.casefold()}
                    if result["original_name"]:
                        skip.add(result["original_name"].casefold())
                    result["other_aliases"] = [
                        a for a in _json.loads(aliases_cached)
                        if a.casefold() not in skip
                    ]
    except Exception:
        pass
    return result


_DEFAULT_QUALITY_PRIORITY: list[str] = [
    "flac:24", "flac:16",
    "mp3:320", "opus:320", "m4a:320",
    "mp3:256", "opus:256", "m4a:256",
    "mp3:192", "opus:192", "m4a:192",
    "mp3:128", "opus:128", "m4a:128",
    "mp3:96",  "opus:96",  "m4a:96",
    "mp3:64",  "opus:64",  "m4a:64",
]
_LOSSY_KBPS_LADDER = [320, 256, 192, 128, 96, 64]


def _expand_quality_token(token: str) -> list[str]:
    q = token.strip().casefold()
    if ":" in q:
        return [q]
    if q == "flac":
        return ["flac:24", "flac:16"]
    if q in ("mp3", "opus", "ogg", "m4a", "aac", "vorbis"):
        return [f"{q}:{kbps}" for kbps in _LOSSY_KBPS_LADDER]
    return [q]


def _parse_quality(quality: str) -> tuple[str, str]:
    container, _, spec = quality.strip().casefold().partition(":")
    return container, spec


def _auto_download_min_score() -> float:
    try:
        cfg = get_config()
        raw = cfg["gui"]["discovery"]["auto_download"]["min_score"].get(float)
        if isinstance(raw, (int, float)):
            return max(0.0, min(1.0, float(raw)))
    except Exception:
        pass
    return 0.0


def _auto_download_quality_priority() -> list[str]:
    try:
        cfg = get_config()
        raw = cfg["gui"]["discovery"]["auto_download"]["quality_priority"].get(list)
        if isinstance(raw, list) and raw:
            result: list[str] = []
            for item in raw:
                result.extend(_expand_quality_token(str(item).strip()))
            return result
    except Exception:
        pass
    return list(_DEFAULT_QUALITY_PRIORITY)


def _deemix_bitrate_for_quality(quality: str) -> str | None:
    container, spec = _parse_quality(quality)
    if container in ("320",):
        return "3"
    if container in ("128",):
        return "1"
    if container == "flac":
        return None if spec == "24" else "9"
    if container == "mp3":
        try:
            kbps = int(spec) if spec else 320
        except ValueError:
            kbps = 320
        if kbps >= 320:
            return "3"
        if kbps == 128:
            return "1"
    return None


def _deemix_account_can_do(quality: str, max_quality: str) -> bool:
    bitrate = _deemix_bitrate_for_quality(quality)
    if bitrate is None:
        return False
    if bitrate == "9":
        return max_quality == "flac"
    if bitrate == "3":
        return max_quality in ("flac", "320")
    return True


def _squidwtf_code_for_quality(quality: str) -> str | None:
    container, spec = _parse_quality(quality)
    if container == "flac":
        return "6" if spec == "16" else "27"
    if container == "mp3":
        try:
            kbps = int(spec) if spec else 320
        except ValueError:
            kbps = 320
        return "5" if kbps >= 320 else None
    return None


_LOSSY_HIGH_KBPS: dict[str, int] = {
    "mp3": 320, "opus": 192, "m4a": 256, "aac": 256, "ogg": 192, "vorbis": 192,
}
_LOSSY_MED_KBPS: dict[str, int] = {
    "mp3": 160, "opus": 96, "m4a": 96, "aac": 96, "ogg": 96, "vorbis": 96,
}


def _lossy_tier(container: str, kbps: float) -> int:
    if kbps >= _LOSSY_HIGH_KBPS.get(container, 192):
        return 2
    if kbps >= _LOSSY_MED_KBPS.get(container, 96):
        return 1
    return 0


def _slskd_candidate_matches_quality(candidate: dict, quality: str) -> bool:
    ext = str(candidate.get("extension") or "").casefold()
    container, spec = _parse_quality(quality)
    if container == "aac":
        container = "m4a"
    if ext == "aac":
        ext = "m4a"
    if ext != container:
        return False
    if not spec:
        return True
    if container == "flac":
        try:
            bits = int(spec)
        except ValueError:
            return True
        if bits >= 24:
            return int(candidate.get("bitDepth") or 0) >= 24 or int(candidate.get("sampleRate") or 0) >= 88200
        return True
    try:
        target_kbps = float(spec)
    except ValueError:
        return True
    mean = candidate.get("meanAudioBitrateKbps")
    if mean is None:
        return True
    return _lossy_tier(container, float(mean)) >= _lossy_tier(container, target_kbps)


def _search_query_variants(artist: str, album: str) -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = [(artist, album)]
    fa, fb = _strip_accents(artist), _strip_accents(album)
    if (fa, fb) != (artist, album):
        variants.append((fa, fb))
    return variants


def _deemix_available_quality(account_quality: dict | None) -> str:
    if not isinstance(account_quality, dict):
        return "128"

    container = str(account_quality.get("container") or "").casefold()
    kbps_val = account_quality.get("kbps")
    try:
        kbps = int(kbps_val) if kbps_val is not None else None
    except Exception:
        kbps = None

    if "flac" in container or "lossless" in container:
        return "flac"
    if kbps is not None and kbps >= 1000:
        return "flac"
    if kbps is not None and kbps >= 320:
        return "320"
    return "128"


async def _schedule_download_from_payload(data: dict) -> tuple[dict, int]:
    provider = str(data.get("provider", "deemix")).strip().casefold()
    album = str(data.get("album", ""))
    artist = str(data.get("artist", ""))
    release_id = str(data.get("release_id", "")).strip() or None
    quality = str(data.get("quality", "flac")).strip().casefold() or "flac"
    output_path = _provider_download_path(provider)

    log.info(
        "Download request provider=%s quality=%s artist=%s album=%s release_id=%s output=%s",
        provider, quality, artist, album, release_id, output_path,
    )

    if provider == "deemix":
        deezer_id = str(data.get("deezer_id", "")).strip() or None
        dcfg = _deemix_settings()

        if not deezer_id:
            if not (artist.strip() or album.strip()):
                return ({"error": "deezer_id or (artist+album) is required"}, 400)
            deezer_id = await deemix_provider.resolve_deezer_id_for_album(
                artist=artist, album=album, timeout_seconds=dcfg["timeout_seconds"],
            )
            if not deezer_id:
                return ({"error": "Could not resolve Deezer release for deemix download"}, 404)

        job = create_download_job(
            provider="deemix", deezer_id=deezer_id, album=album, artist=artist, release_id=release_id,
        )
        asyncio.ensure_future(
            run_deemix_download(
                job_id=job["job_id"], deezer_id=deezer_id, output_path=output_path,
                base_url=dcfg["base_url"], timeout_seconds=dcfg["timeout_seconds"],
                auth_header=dcfg["auth_header"], arl=dcfg["arl"],
                bitrate=_deemix_bitrate_for_quality(quality) or "9",
            )
        )
        return (job, 202)

    if provider == "slskd":
        if not album.strip() and not artist.strip():
            return ({"error": "artist or album required"}, 400)

        scfg = _slskd_settings()
        selected_candidate = data.get("candidate")
        job = create_download_job(provider="slskd", album=album, artist=artist, release_id=release_id)
        asyncio.ensure_future(
            run_slskd_download(
                job_id=job["job_id"], artist=artist, album=album, output_path=output_path,
                base_url=scfg["base_url"], api_key=scfg["api_key"], timeout_seconds=scfg["timeout_seconds"],
                selected_candidate=selected_candidate if isinstance(selected_candidate, dict) else None,
            )
        )
        return (job, 202)

    if provider == "squidwtf":
        if not album.strip() and not artist.strip():
            return ({"error": "artist or album required"}, 400)

        wcfg = _squidwtf_settings()
        squid_album_id = str(data.get("squid_album_id", "")).strip() or None
        if not squid_album_id:
            match = await squidwtf_provider.resolve_squidwtf_match_for_album(
                artist=artist, album=album, timeout_seconds=min(20, wcfg["timeout_seconds"]), base_url=wcfg["base_url"],
            )
            if not match:
                return ({"error": "Could not resolve SquidWTF release"}, 404)
            squid_album_id = str(match.get("squid_album_id") or "").strip() or None
            if not squid_album_id:
                return ({"error": "SquidWTF album id missing in match"}, 502)

        job = create_download_job(
            provider="squidwtf", squid_album_id=squid_album_id, album=album, artist=artist, release_id=release_id,
        )
        asyncio.ensure_future(
            run_squidwtf_download(
                job_id=job["job_id"], artist=artist, album=album, squid_album_id=squid_album_id,
                output_path=output_path, base_url=wcfg["base_url"], timeout_seconds=wcfg["timeout_seconds"],
                quality=squidwtf_provider.normalize_squidwtf_quality(
                    str(data.get("squid_quality", "27")).strip() or "27"
                ),
            )
        )
        return (job, 202)

    return ({"error": "provider must be 'deemix', 'slskd' or 'squidwtf'"}, 400)


async def _find_best_match_across_providers(
    album_payload: dict,
    providers: list[str],
    qualities: list[str] | None = None,
) -> dict | None:
    artist = str(album_payload.get("artist", "")).strip()
    album = str(album_payload.get("album", "")).strip()

    if not artist and not album:
        log.warning("_find_best_match: no artist or album")
        return None

    min_score = _auto_download_min_score()

    if qualities:
        quality_priority: list[str] = []
        for q in qualities:
            quality_priority.extend(_expand_quality_token(q))
    else:
        quality_priority = _auto_download_quality_priority()

    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    wcfg = _squidwtf_settings()

    deemix_id: str | None = str(album_payload.get("deezer_id", "")).strip() or None
    deemix_score: float = 1.0
    deemix_max_quality = "128"
    deemix_title: str | None = None

    if "deemix" in providers and dcfg["base_url"]:
        try:
            aq = await deemix_provider.resolve_quality_from_arl(
                base_url=dcfg["base_url"], timeout_seconds=dcfg["timeout_seconds"],
                auth_header=dcfg["auth_header"], arl=dcfg["arl"],
            )
        except Exception as exc:
            log.warning("_find_best_match: deemix quality detection failed: %s", exc)
            aq = None
        deemix_max_quality = _deemix_available_quality(aq)

        if not deemix_id:
            for q_artist, q_album in _search_query_variants(artist, album):
                try:
                    m = await deemix_provider.resolve_deezer_match_for_album(
                        artist=q_artist, album=q_album, timeout_seconds=dcfg["timeout_seconds"],
                    )
                    if m:
                        deemix_id = m.get("deezer_id")
                        deemix_score = float(m.get("score") or 0.0)
                        deemix_title = str(m.get("title") or album)
                        break
                except Exception as exc:
                    log.debug("deemix match search failed: %s", exc)

    slskd_ranked: list[dict] = []
    if "slskd" in providers and scfg["base_url"]:
        try:
            candidates = await slskd_provider.search_album(
                base_url=scfg["base_url"], api_key=scfg["api_key"],
                artist=artist, album=album, timeout_seconds=scfg["timeout_seconds"],
            )
            slskd_ranked = slskd_provider.rank_candidates(candidates, album_hint=album)
        except Exception as exc:
            log.debug("slskd search failed: %s", exc)

    squid_id: str | None = str(album_payload.get("squid_album_id", "")).strip() or None
    squid_title: str | None = None
    if "squidwtf" in providers and wcfg["base_url"] and not squid_id:
        try:
            m = await squidwtf_provider.resolve_squidwtf_match_for_album(
                artist=artist, album=album, timeout_seconds=min(20, wcfg["timeout_seconds"]), base_url=wcfg["base_url"],
            )
            if m:
                squid_id = str(m.get("squid_album_id") or "").strip() or None
                squid_title = str(m.get("title") or album)
        except Exception as exc:
            log.debug("squidwtf search failed: %s", exc)

    for quality in quality_priority:
        results: list[tuple[float, dict]] = []

        if deemix_id and "deemix" in providers and dcfg["base_url"]:
            if _deemix_account_can_do(quality, deemix_max_quality):
                payload = dict(album_payload)
                payload.update({"provider": "deemix", "quality": quality, "deezer_id": deemix_id})
                results.append((deemix_score, payload))

        if slskd_ranked and "slskd" in providers and scfg["base_url"]:
            matching = [c for c in slskd_ranked if _slskd_candidate_matches_quality(c, quality)]
            if matching:
                best = matching[0]
                score = float(slskd_provider.score_candidate(best, album_hint=album))
                payload = dict(album_payload)
                payload.update({"provider": "slskd", "quality": quality, "candidate": best})
                results.append((score, payload))

        if squid_id and "squidwtf" in providers and wcfg["base_url"]:
            squid_code = _squidwtf_code_for_quality(quality)
            if squid_code:
                payload = dict(album_payload)
                payload.update({
                    "provider": "squidwtf", "quality": quality,
                    "squid_album_id": squid_id, "squid_quality": squid_code,
                })
                results.append((1.0, payload))

        if results:
            qualified = [(s, p) for s, p in results if s >= min_score]
            if not qualified:
                log.info(
                    "_find_best_match: all results below min_score=%.2f for artist=%s album=%s quality=%s",
                    min_score, artist, album, quality,
                )
                continue
            best_score, best_payload = max(qualified, key=lambda x: x[0])
            # Inject match metadata for probe-and-queue callers (stripped before scheduling).
            best_payload["_match_score"] = best_score
            selected_provider = best_payload.get("provider", "")
            if selected_provider == "deemix":
                best_payload["_result_title"] = deemix_title or album
            elif selected_provider == "slskd":
                candidate = best_payload.get("candidate") or {}
                best_payload["_result_title"] = (candidate.get("folder", "").rsplit("/", 1)[-1]) or album
            elif selected_provider == "squidwtf":
                best_payload["_result_title"] = squid_title or album
            else:
                best_payload["_result_title"] = album
            log.info(
                "_find_best_match: selected provider=%s quality=%s score=%.2f",
                selected_provider, quality, best_score,
            )
            return best_payload

    log.warning("_find_best_match: no match found for artist=%s album=%s", artist, album)
    return None


# ─── Module-level probe functions (shared by download_options + probe_and_queue) ─


async def _probe_deemix(
    artist: str,
    album: str,
    original_name: str | None,
    other_aliases: list[str],
    dcfg: dict,
) -> list[dict]:
    if not dcfg["base_url"]:
        return []
    try:
        account_quality = await deemix_provider.resolve_quality_from_arl(
            base_url=dcfg["base_url"], timeout_seconds=dcfg["timeout_seconds"],
            auth_header=dcfg["auth_header"], arl=dcfg["arl"],
        )
    except Exception:
        account_quality = None

    async def _try(q_artist: str) -> dict | None:
        names = [q_artist]
        stripped = _strip_accents(q_artist)
        if stripped != q_artist:
            names.append(stripped)
        for n in names:
            try:
                m = await deemix_provider.resolve_deezer_match_for_album(
                    artist=n, album=album, timeout_seconds=dcfg["timeout_seconds"]
                )
                if m:
                    return m
            except Exception:
                pass
        return None

    primary_task = asyncio.create_task(_try(artist))
    orig_task = asyncio.create_task(_try(original_name)) if original_name else None
    primary_match = await primary_task
    orig_match = await orig_task if orig_task else None

    log.info("probe_deemix artist=%r found=%s", artist, bool(primary_match))
    if original_name:
        log.info("probe_deemix original_name=%r found=%s", original_name, bool(orig_match))

    match = primary_match or orig_match
    if not match:
        for alias in other_aliases:
            match = await _try(alias)
            log.info("probe_deemix alias=%r found=%s", alias, bool(match))
            if match:
                break

    if not match:
        return []
    known = _artist_known_names_set(artist, original_name, other_aliases)
    returned_artist = str(match.get("artist") or "")
    artist_ok = _strip_accents(returned_artist).casefold() in known
    if not artist_ok:
        log.info("probe_deemix artist mismatch returned=%r known=%r", returned_artist, sorted(known))
    aq = account_quality or {}
    return [_download_suggestion_summary(
        provider="deemix",
        score=float(match.get("score") or 0.0) if artist_ok else 0.0,
        title=str(match.get("title") or album),
        artist=returned_artist or artist,
        details={
            "deezer_id": match.get("deezer_id"),
            "trackCount": match.get("track_count"),
            "container": aq.get("container") or match.get("container"),
            "kbps": aq.get("kbps") if aq.get("kbps") is not None else match.get("kbps"),
            "url": f"https://www.deezer.com/album/{match.get('deezer_id')}",
        },
    )]


async def _probe_slskd(
    artist: str,
    album: str,
    original_name: str | None,
    other_aliases: list[str],
    scfg: dict,
    expected_track_count: int | None = None,
    expected_tracks: list[dict] | None = None,
    run_original_name: bool = True,
    original_name_only: bool = False,
) -> list[dict]:
    """Search slskd for album candidates.

    Modes (mutually exclusive flags):
    - default (run_original_name=True): primary alias → original_name → combined; used by probe_and_queue
    - run_original_name=False: primary alias only, returns fast; used by download_options phase 1
    - original_name_only=True: original_name only, no primary; used by download_options phase 2
    """
    if not scfg["base_url"]:
        return []

    async def _try(q_artist: str) -> list:
        return await slskd_provider.search_album(
            base_url=scfg["base_url"], api_key=scfg["api_key"],
            artist=q_artist, album=album, timeout_seconds=scfg["timeout_seconds"],
        )

    if original_name_only:
        if not original_name or original_name.casefold() == artist.casefold():
            return []
        candidates = await _try(original_name)
        log.info("probe_slskd original_name_only=%r candidates=%d", original_name, len(candidates))
    else:
        candidates = await _try(artist)
        log.info("probe_slskd artist=%r candidates=%d", artist, len(candidates))
        if run_original_name and original_name and original_name.casefold() != artist.casefold():
            await asyncio.sleep(1)
            orig_candidates = await _try(original_name)
            log.info("probe_slskd original_name=%r candidates=%d", original_name, len(orig_candidates))
            seen = {(c.get("username"), c.get("folder")) for c in candidates}
            for c in orig_candidates:
                key = (c.get("username"), c.get("folder"))
                if key not in seen:
                    candidates.append(c)
                    seen.add(key)
        if not candidates:
            for alias in other_aliases:
                candidates = await _try(alias)
                log.info("probe_slskd alias=%r candidates=%d", alias, len(candidates))
                if candidates:
                    break

    ranked = slskd_provider.rank_candidates(
        candidates,
        artist_hint=artist,
        album_hint=album,
        expected_track_count=expected_track_count,
        expected_tracks=expected_tracks,
        speed_min_bps=scfg.get("speed_min_bps", 1_000_000),
        queue_max=scfg.get("queue_max", 100),
    )
    return [
        _download_suggestion_summary(
            provider="slskd",
            score=float(slskd_provider.score_candidate(
                c,
                artist_hint=artist,
                album_hint=album,
                expected_track_count=expected_track_count,
                expected_tracks=expected_tracks,
                speed_min_bps=scfg.get("speed_min_bps", 1_000_000),
                queue_max=scfg.get("queue_max", 100),
            )),
            title=(c.get("folder", "").rsplit("/", 1)[-1] or album),
            artist=artist,
            details={
                "searchId": c.get("searchId"), "username": c.get("username"),
                "folder": c.get("folder"), "fileCount": len(c.get("files") or []),
                "audioFileCount": c.get("audioFileCount"), "meanAudioBitrateKbps": c.get("meanAudioBitrateKbps"),
                "extension": c.get("extension"), "sampleRate": c.get("sampleRate"),
                "bitDepth": c.get("bitDepth"), "uploadSpeed": c.get("uploadSpeed"),
                "queueLength": c.get("queueLength"), "hasFreeUploadSlot": c.get("hasFreeUploadSlot"),
                "totalSize": c.get("totalSize"), "candidate": c,
            },
        )
        for c in ranked[:20]
    ]


async def _probe_squidwtf(
    artist: str,
    album: str,
    original_name: str | None,
    other_aliases: list[str],
    wcfg: dict,
) -> list[dict]:
    if not wcfg["base_url"]:
        return []

    async def _try(q_artist: str) -> dict | None:
        return await squidwtf_provider.resolve_squidwtf_match_for_album(
            artist=q_artist, album=album,
            timeout_seconds=min(20, wcfg["timeout_seconds"]), base_url=wcfg["base_url"],
        )

    primary_task = asyncio.create_task(_try(artist))
    orig_task = asyncio.create_task(_try(original_name)) if original_name else None
    primary_match = await primary_task
    orig_match = await orig_task if orig_task else None

    log.info("probe_squidwtf artist=%r found=%s", artist, bool(primary_match))
    if original_name:
        log.info("probe_squidwtf original_name=%r found=%s", original_name, bool(orig_match))

    match = primary_match or orig_match
    if not match:
        for alias in other_aliases:
            match = await _try(alias)
            log.info("probe_squidwtf alias=%r found=%s", alias, bool(match))
            if match:
                break

    if not match:
        return []
    known = _artist_known_names_set(artist, original_name, other_aliases)
    returned_artist = str(match.get("artist") or "")
    artist_ok = _strip_accents(returned_artist).casefold() in known
    if not artist_ok:
        log.info("probe_squidwtf artist mismatch returned=%r known=%r", returned_artist, sorted(known))
    squid_album_id = match.get("squid_album_id")
    base_score = float(match.get("score") or 0.0) if artist_ok else 0.0
    results = []
    for q_alias, q_code in [("flac:hires", "27"), ("flac:16", "6"), ("mp3:320", "5")]:
        qi = squidwtf_provider.quality_label_to_display(q_alias)
        results.append(_download_suggestion_summary(
            provider="squidwtf", score=base_score,
            title=str(match.get("title") or album), artist=returned_artist or artist,
            details={
                "squid_album_id": squid_album_id, "trackCount": match.get("track_count"),
                "quality": q_code, "container": qi.get("container"), "kbps": qi.get("kbps"),
                "source": "qobuz",
                "url": f"{wcfg['base_url'].rstrip('/')}/api/get-album?album_id={squid_album_id}",
            },
        ))
    return results


# ─── Auto-selection helpers (probe_and_queue) ────────────────────────────────


def _suggestion_matches_quality(sugg: dict, quality: str) -> bool:
    """Return True if a DownloadSuggestion can fulfil the given quality token."""
    provider = str(sugg.get("provider", ""))
    details = sugg.get("details") or {}
    container, spec = _parse_quality(quality)

    if provider == "squidwtf":
        code_map = {"27": "flac:24", "6": "flac:16", "5": "mp3:320"}
        sugg_token = code_map.get(str(details.get("quality", "")))
        if sugg_token is None:
            return False
        sc, ss = _parse_quality(sugg_token)
        return sc == container and ss == spec

    if provider == "deemix":
        sc = str(details.get("container") or "").casefold()
        if container == "flac":
            if sc not in ("flac", "alac", "wav", "aiff"):
                return False
            if spec == "24":
                kbps = details.get("kbps")
                return bool(kbps) and float(kbps) > 1600
            return True
        if sc != container:
            return False
        kbps = details.get("kbps")
        if kbps is not None and spec:
            try:
                return _lossy_tier(container, float(kbps)) >= _lossy_tier(container, float(spec))
            except (ValueError, TypeError):
                pass
        return True

    if provider == "slskd":
        ext = str(details.get("extension") or "").casefold()
        if ext == "aac":
            ext = "m4a"
        actual = "m4a" if container == "aac" else container
        if ext != actual:
            return False
        if container == "flac":
            if spec == "24":
                bd = details.get("bitDepth")
                sr = details.get("sampleRate")
                return bool(bd and int(bd) >= 24) or bool(sr and int(sr) >= 88200)
            return True
        mean = details.get("meanAudioBitrateKbps")
        if mean is not None and spec:
            try:
                return _lossy_tier(container, float(mean)) >= _lossy_tier(container, float(spec))
            except (ValueError, TypeError):
                pass
        return True

    return False


# Higher value = higher priority in max() comparisons.
_PROVIDER_PRIORITY: dict[str, int] = {"squidwtf": 2, "deemix": 1, "slskd": 0}


def _suggestion_sort_key(s: dict) -> tuple[float, int, float]:
    """Sort key: score, then provider priority, then slskd upload speed."""
    score = float(s.get("score", 0))
    prio = _PROVIDER_PRIORITY.get(str(s.get("provider", "")), 0)
    details = s.get("details") or {}
    upload_speed = float(details.get("uploadSpeed", 0)) if s.get("provider") == "slskd" else 0.0
    return (score, prio, upload_speed)


def _auto_select_suggestion(
    suggestions: list[dict],
    quality_priority: list[str],
    min_score: float,
) -> tuple[dict, str] | tuple[None, None]:
    """Pick best suggestion: quality tier first, then score, provider, slskd speed."""
    for quality in quality_priority:
        qualified = [
            s for s in suggestions
            if _suggestion_matches_quality(s, quality) and float(s.get("score", 0)) >= min_score
        ]
        if qualified:
            best = max(qualified, key=_suggestion_sort_key)
            log.info(
                "_auto_select: quality=%s score=%.2f provider=%s title=%r",
                quality, float(best.get("score", 0)), best.get("provider"), best.get("title"),
            )
            return best, quality
    return None, None


def _build_schedule_payload(
    sugg: dict,
    artist: str,
    album: str,
    release_id: str | None,
) -> dict[str, Any]:
    """Convert a DownloadSuggestion to a _schedule_download_from_payload compatible dict."""
    provider = str(sugg.get("provider", ""))
    details = sugg.get("details") or {}
    payload: dict[str, Any] = {"provider": provider, "artist": artist, "album": album}
    if release_id:
        payload["release_id"] = release_id

    if provider == "deemix":
        payload["deezer_id"] = str(details.get("deezer_id") or "")
        sc = str(details.get("container") or "").casefold()
        kbps = details.get("kbps")
        if sc in ("flac", "alac", "wav", "aiff"):
            payload["quality"] = "flac:24" if (kbps and float(kbps) > 1600) else "flac:16"
        elif kbps and float(kbps) >= 256:
            payload["quality"] = "mp3:320"
        else:
            payload["quality"] = "mp3:128"
    elif provider == "squidwtf":
        payload["squid_album_id"] = str(details.get("squid_album_id") or "")
        payload["squid_quality"] = str(details.get("quality") or "27")
    elif provider == "slskd":
        payload["candidate"] = details.get("candidate")

    return payload


# ─────────────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/discovery", tags=["discovery"])


# ─── Quality ─────────────────────────────────────────────────────────────────


@router.get("/quality-priority")
async def get_quality_priority() -> dict:
    return {"quality_priority": _auto_download_quality_priority()}


# ─── Artist search / follow ───────────────────────────────────────────────────


def _extract_en_fr_alias(artist_data: dict) -> str | None:
    """Return the best EN/FR primary display alias from a MusicBrainz artist object.

    Priority: EN primary > FR primary > EN non-primary > FR non-primary.
    """
    aliases = artist_data.get("aliases") or []
    en_primary: str | None = None
    fr_primary: str | None = None
    en_any: str | None = None
    fr_any: str | None = None
    for alias in aliases:
        locale = alias.get("locale") or ""
        alias_type = alias.get("type") or ""
        if locale not in ("en", "fr"):
            continue
        if alias_type not in ("Artist name", "Legal name", ""):
            continue
        candidate = str(alias.get("name") or alias.get("alias") or "").strip()
        if not candidate:
            continue
        is_primary = alias.get("primary") is True
        if locale == "en":
            if is_primary and en_primary is None:
                en_primary = candidate
            elif not is_primary and en_any is None:
                en_any = candidate
        elif locale == "fr":
            if is_primary and fr_primary is None:
                fr_primary = candidate
            elif not is_primary and fr_any is None:
                fr_any = candidate
    return en_primary or fr_primary or en_any or fr_any


async def _search_mb_artists(q: str) -> list[dict]:
    base_url = _musicbrainz_api_base_url()
    url = f"{base_url}/artist?query={quote(q)}&limit=15&inc=aliases&fmt=json"
    headers = {"User-Agent": "beets-flask/1.0 ( https://github.com/pSpitzner/beets-flask )"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        return data.get("artists", [])
    except Exception as exc:
        log.warning("MusicBrainz artist search failed: %s", exc)
        return []


async def _search_deezer_artists(q: str) -> list[dict]:
    url = f"https://api.deezer.com/search/artist?q={quote(q)}&limit=15"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json(content_type=None)
        return data.get("data", [])
    except Exception as exc:
        log.warning("Deezer artist search failed: %s", exc)
        return []


@router.get("/search/artists")
async def search_artists(q: str = "") -> list:
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")

    mb_results, deezer_results = await asyncio.gather(
        _search_mb_artists(q),
        _search_deezer_artists(q),
    )

    # Build Deezer lookup: normalized_name → deezer_id
    deezer_by_name: dict[str, int] = {}
    for d in deezer_results:
        norm = _strip_accents(str(d.get("name") or "")).strip().casefold()
        if norm:
            deezer_by_name[norm] = int(d["id"])

    seen_normalized: set[str] = set()
    results: list[dict] = []

    for a in mb_results:
        alias = _extract_en_fr_alias(a)
        original = str(a.get("name") or "").strip()
        # Only substitute alias for non-Latin-script names (CJK, Arabic, …).
        # Latin-based names — including diacritics — are correct as-is; aliases
        # are typically legal names that should not replace a stage name.
        needs_alias = any(unicodedata.category(c) == "Lo" for c in original)
        primary = (alias if needs_alias else None) or original
        norm = _strip_accents(primary).strip().casefold()
        if not primary or norm in seen_normalized:
            continue
        seen_normalized.add(norm)

        deezer_id = deezer_by_name.pop(norm, None)
        # Also try matching against the raw original when alias differs
        if deezer_id is None and alias:
            orig_norm = _strip_accents(original).strip().casefold()
            deezer_id = deezer_by_name.pop(orig_norm, None)

        results.append({
            "id": a.get("id"),
            "name": primary,
            "original_name": original if original != primary else None,
            "sort_name": a.get("sort-name", ""),
            "disambiguation": a.get("disambiguation", ""),
            "country": a.get("country", ""),
            "score": a.get("score", 0),
            "tracked": is_tracked(primary),
            "mb_url": f"https://musicbrainz.org/artist/{a['id']}" if a.get("id") else None,
            "deezer_id": deezer_id,
        })

    # Remaining Deezer-only artists not matched to MB
    for d in deezer_results:
        norm = _strip_accents(str(d.get("name") or "")).strip().casefold()
        if norm not in deezer_by_name or norm in seen_normalized:
            continue
        name = str(d.get("name") or "").strip()
        seen_normalized.add(norm)
        results.append({
            "id": None,
            "name": name,
            "original_name": None,
            "sort_name": None,
            "disambiguation": None,
            "country": None,
            "score": 0,
            "tracked": is_tracked(name),
            "mb_url": None,
            "deezer_id": int(d["id"]),
        })

    return results


@router.get("/artists")
async def list_tracked_artists() -> list:
    artists = get_tracked_artists()
    missing_map = get_missing_count_map()
    for a in artists:
        a["missing_count"] = missing_map.get(normalize_artist_key(a["name"]), 0)
    return artists


@router.post("/artists", status_code=201)
async def add_artist(
    _user: CurrentUser,
    data: dict[str, Any] = Body(default_factory=dict),
) -> dict:
    if not data or not str(data.get("name", "")).strip():
        raise HTTPException(status_code=400, detail="name is required")
    name = str(data["name"]).strip()
    raw_orig = data.get("original_name")
    original_name = str(raw_orig).strip() if raw_orig and str(raw_orig).strip() else None
    return add_tracked_artist(name, original_name=original_name)


@router.delete("/artists/{name:path}")
async def remove_artist(name: str, lib: BeetsLib, _user: CurrentUser) -> dict:
    """Remove artist globally: delete all beets library albums then drop tracking row."""
    tracked = get_tracked_artist(name)
    names_to_search = [name]
    if tracked and tracked.get("original_name"):
        names_to_search.append(tracked["original_name"])

    # Collect albums by all name variants
    albums_seen: set[int] = set()
    albums_to_delete = []
    normalized_variants = {n.strip().casefold() for n in names_to_search}
    for variant in names_to_search:
        with lib.transaction() as tx:
            rows = tx.query("SELECT id FROM albums WHERE instr(albumartist, ?) > 0", (variant,))
        for row in rows:
            if row[0] in albums_seen:
                continue
            album = lib.get_album(row[0])
            if album is None:
                continue
            albumartist = str(getattr(album, "albumartist", "") or "").strip().casefold()
            if albumartist in normalized_variants:
                albums_seen.add(row[0])
                albums_to_delete.append(album)

    if albums_to_delete:
        delete_entities(albums_to_delete, delete_files=True)

    remove_tracked_artist(name)

    for n in names_to_search:
        invalidate_missing_cache_for_string(n)
    invalidate_artists_cache()

    return {"ok": True, "albums_deleted": len(albums_to_delete)}


@router.get("/artists/{name:path}/status")
async def tracked_artist_status(name: str) -> dict:
    return {"name": name, "tracked": is_tracked(name)}


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


@router.post("/download/probe-and-queue")
async def probe_and_queue(data: dict[str, Any] = Body(default_factory=dict)):
    """Probe providers and queue the best match for a single album.

    Returns ``{"status": "queued"|"not_found"|"error", "provider"?, "score"?, "result_title"?, "job_id"?}``.
    """
    if not data:
        raise HTTPException(status_code=400, detail="request body is required")

    artist = str(data.get("artist", "")).strip()
    album = str(data.get("album", "")).strip()
    if not artist and not album:
        raise HTTPException(status_code=400, detail="artist or album required")

    providers_raw = data.get("providers", [])
    providers = [str(p).strip().casefold() for p in (providers_raw if isinstance(providers_raw, list) else [])]
    providers = [p for p in providers if p in ("deemix", "slskd", "squidwtf")] or ["deemix", "slskd", "squidwtf"]

    qualities_raw = data.get("qualities") or None
    qualities: list[str] | None = None
    if isinstance(qualities_raw, list) and qualities_raw:
        qualities = [str(q).strip() for q in qualities_raw if str(q).strip()]

    release_id = str(data.get("release_id", "")).strip() or None
    _etr = data.get("expected_tracks")
    expected_tracks: list[dict] | None = (
        [t for t in _etr if isinstance(t, dict)] if isinstance(_etr, list) and _etr else None
    )

    fallbacks = _get_artist_search_fallbacks(artist)
    original_name: str | None = fallbacks["original_name"]
    other_aliases: list[str] = fallbacks["other_aliases"]

    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    wcfg = _squidwtf_settings()

    # Run all selected providers in parallel; wait for ALL before selecting.
    provider_tasks: list[tuple[str, asyncio.Task]] = []
    if "slskd" in providers:
        provider_tasks.append(("slskd", asyncio.create_task(
            _probe_slskd(
                artist, album, original_name, other_aliases, scfg,
                expected_tracks=expected_tracks,
            )
        )))
    if "deemix" in providers:
        provider_tasks.append(("deemix", asyncio.create_task(
            _probe_deemix(artist, album, original_name, other_aliases, dcfg)
        )))
    if "squidwtf" in providers:
        provider_tasks.append(("squidwtf", asyncio.create_task(
            _probe_squidwtf(artist, album, original_name, other_aliases, wcfg)
        )))

    all_suggestions: list[dict] = []
    for pname, task in provider_tasks:
        try:
            all_suggestions += await task
        except Exception as exc:
            log.warning("probe_and_queue %s failed: %r", pname, exc)

    if qualities:
        quality_priority: list[str] = []
        for q in qualities:
            quality_priority.extend(_expand_quality_token(q))
    else:
        quality_priority = _auto_download_quality_priority()

    min_score = _auto_download_min_score()
    best_sugg, best_quality = _auto_select_suggestion(all_suggestions, quality_priority, min_score)

    from fastapi.responses import JSONResponse
    if best_sugg is None:
        best_rejected: dict[str, Any] | None = None
        if all_suggestions:
            # Same as _auto_select_suggestion but without min_score filter.
            best_overall: dict | None = None
            best_rej_quality = ""
            for quality in quality_priority:
                qualified = [
                    s for s in all_suggestions
                    if _suggestion_matches_quality(s, quality)
                ]
                if qualified:
                    best_overall = max(qualified, key=_suggestion_sort_key)
                    best_rej_quality = quality
                    break
            if best_overall is None:
                best_overall = max(all_suggestions, key=_suggestion_sort_key)
            best_rejected = {
                "provider": str(best_overall.get("provider", "")),
                "score": float(best_overall.get("score", 0.0)),
                "title": str(best_overall.get("title", album)),
                "quality": best_rej_quality,
                "details": best_overall.get("details") or {},
            }
        content: dict[str, Any] = {"status": "not_found", "artist": artist, "album": album}
        if best_rejected:
            content["best_rejected"] = best_rejected
        return JSONResponse(content=content, status_code=200)

    schedule_payload = _build_schedule_payload(best_sugg, artist, album, release_id)
    job_or_error, status = await _schedule_download_from_payload(schedule_payload)

    provider_name = str(best_sugg.get("provider", ""))
    match_score = float(best_sugg.get("score", 0.0))
    result_title = str(best_sugg.get("title", album))

    if 200 <= status < 300:
        return JSONResponse(
            content={
                "status": "queued",
                "provider": provider_name,
                "score": match_score,
                "result_title": result_title,
                "quality": best_quality or "",
                "job_id": job_or_error.get("job_id"),
            },
            status_code=202,
        )
    return JSONResponse(
        content={
            "status": "error",
            "provider": provider_name,
            "score": match_score,
            "result_title": result_title,
            "error": str(job_or_error.get("error", "Download scheduling failed")),
        },
        status_code=status,
    )


@router.post("/download/options")
async def download_options(data: dict[str, Any] = Body(default_factory=dict)):
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
    _etr = data.get("expected_tracks")
    expected_tracks: list[dict] | None = (
        [t for t in _etr if isinstance(t, dict)] if isinstance(_etr, list) and _etr else None
    )

    if not artist and not album:
        raise HTTPException(status_code=400, detail="artist or album required")
    if provider_filter and provider_filter not in ("deemix", "slskd", "squidwtf"):
        raise HTTPException(status_code=400, detail="provider must be 'deemix', 'slskd' or 'squidwtf' when set")

    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    wcfg = _squidwtf_settings()
    _fallbacks = _get_artist_search_fallbacks(artist)
    artist_original_name: str | None = _fallbacks["original_name"]
    artist_other_aliases: list[str] = _fallbacks["other_aliases"]

    deemix_opts = slskd_opts = squidwtf_opts = []
    if provider_filter == "deemix":
        try:
            deemix_opts = await _probe_deemix(artist, album, artist_original_name, artist_other_aliases, dcfg)
        except Exception as exc:
            log.warning("probe_deemix failed: %r", exc)
    elif provider_filter == "slskd":
        extended = bool(data.get("extended"))
        try:
            slskd_opts = await _probe_slskd(
                artist, album, artist_original_name, artist_other_aliases, scfg,
                expected_track_count=expected_track_count,
                expected_tracks=expected_tracks,
                run_original_name=False,
                original_name_only=extended,
            )
        except Exception as exc:
            log.warning("probe_slskd failed: %r", exc)
    elif provider_filter == "squidwtf":
        try:
            squidwtf_opts = await _probe_squidwtf(artist, album, artist_original_name, artist_other_aliases, wcfg)
        except Exception as exc:
            log.warning("probe_squidwtf failed: %r", exc)
    else:
        deemix_task = asyncio.create_task(_probe_deemix(artist, album, artist_original_name, artist_other_aliases, dcfg))
        slskd_task = asyncio.create_task(_probe_slskd(
            artist, album, artist_original_name, artist_other_aliases, scfg,
            expected_track_count=expected_track_count,
            expected_tracks=expected_tracks,
            run_original_name=False,
        ))
        squidwtf_task = asyncio.create_task(_probe_squidwtf(artist, album, artist_original_name, artist_other_aliases, wcfg))
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
