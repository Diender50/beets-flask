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
from beets_flask.library_cache import get_missing_count_map, invalidate_missing_cache_for_string, normalize_artist_key
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
        folders_view = config["gui"]["inbox"]["folders"]
    except Exception as exc:
        log.warning("Could not read inbox folders from config: %s", exc)
        return {}

    result: dict[str, str] = {}
    try:
        # Prefer flattened mapping because it is stable across confuse config layers.
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

            # Allow selecting direct path as selector value.
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

            # Allow selecting direct path as selector value.
            result[path] = path

    # Also include real config keys (Inbox1/Soulseek/etc.) when available.
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
    # `inbox_folder` can be inbox key (Inbox1), inbox name, or direct path.
    selector = _cfg_str(["gui", "discovery", provider, "inbox_folder"], "").strip()
    inbox_paths = _all_inbox_paths()

    if selector and selector in inbox_paths:
        return inbox_paths[selector]

    if selector:
        # Case-insensitive fallback matching for key/name/path.
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
    return {
        "base_url": _cfg_str(base + ["base_url"]),
        "api_key": _cfg_str(base + ["api_key"]) or None,
        "timeout_seconds": _cfg_int(base + ["timeout_seconds"], 40),
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


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


# ── Quality helpers ───────────────────────────────────────────────────────────

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
    """Expand a bare quality alias to specific ordered tokens.

    "flac" → ["flac:24", "flac:16"]
    "mp3"  → ["mp3:320", "mp3:256", "mp3:192", "mp3:128"]
    Already specific tokens (e.g. "flac:16", "mp3:320") pass through unchanged.
    """
    q = token.strip().casefold()
    if ":" in q:
        return [q]
    if q == "flac":
        return ["flac:24", "flac:16"]
    if q in ("mp3", "opus", "ogg", "m4a", "aac", "vorbis"):
        return [f"{q}:{kbps}" for kbps in _LOSSY_KBPS_LADDER]
    return [q]


def _parse_quality(quality: str) -> tuple[str, str]:
    """Return (container, spec) from a token like 'flac:24' or 'mp3:320'."""
    container, _, spec = quality.strip().casefold().partition(":")
    return container, spec


def _auto_download_quality_priority() -> list[str]:
    """Load quality priority list from config, expanding bare tokens."""
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
    """Map a quality token to a deemix bitrate code, or None if not natively supported.

    Deemix/Deezer native tiers: 9=FLAC (16-bit CD), 3=MP3 320, 1=MP3 128.
    flac:24 is not available on Deezer (CD quality only).
    Old bare tokens "320" and "128" are accepted for backward compat.
    """
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
    """Check if the deemix account tier supports this quality level."""
    bitrate = _deemix_bitrate_for_quality(quality)
    if bitrate is None:
        return False
    if bitrate == "9":
        return max_quality == "flac"
    if bitrate == "3":
        return max_quality in ("flac", "320")
    return True  # MP3 128: any account tier


def _squidwtf_code_for_quality(quality: str) -> str | None:
    """Map quality token to a squidwtf quality code, or None if not supported.

    squidwtf supports: 27=FLAC 24-bit, 6=FLAC 16-bit, 5=MP3 320.
    """
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


# Per-codec kbps thresholds for perceptual quality tiers.
# Opus/OGG ~2× more efficient than MP3; AAC/M4A ~1.5×.
_LOSSY_HIGH_KBPS: dict[str, int] = {
    "mp3": 320, "opus": 192, "m4a": 256, "aac": 256, "ogg": 192, "vorbis": 192,
}
_LOSSY_MED_KBPS: dict[str, int] = {
    "mp3": 160, "opus": 96, "m4a": 96, "aac": 96, "ogg": 96, "vorbis": 96,
}


def _lossy_tier(container: str, kbps: float) -> int:
    """Return 2=high, 1=medium, 0=low for a lossy codec at given kbps."""
    if kbps >= _LOSSY_HIGH_KBPS.get(container, 192):
        return 2
    if kbps >= _LOSSY_MED_KBPS.get(container, 96):
        return 1
    return 0


def _slskd_candidate_matches_quality(candidate: dict, quality: str) -> bool:
    """Return True if the slskd candidate satisfies the quality requirement.

    For lossless (FLAC): matches by bitDepth/sampleRate.
    For lossy (VBR-aware): uses per-codec transparency tiers instead of a flat
    kbps tolerance. A candidate matches when its perceptual tier >= the tier of
    the requested quality token, so an opus file at 146 kbps (medium) matches
    opus:128 (medium) but not opus:192 (high).
    """
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
        return True  # flac:16 accepts any FLAC
    try:
        target_kbps = float(spec)
    except ValueError:
        return True
    mean = candidate.get("meanAudioBitrateKbps")
    if mean is None:
        return True  # no bitrate info — optimistically accept
    return _lossy_tier(container, float(mean)) >= _lossy_tier(container, target_kbps)


def _search_query_variants(artist: str, album: str) -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = [(artist, album)]
    fa, fb = _strip_accents(artist), _strip_accents(album)
    if (fa, fb) != (artist, album):
        variants.append((fa, fb))
    return variants


# ─────────────────────────────────────────────────────────────────────────────

def _deemix_available_quality(account_quality: dict | None) -> str:
    """Map deemix account capability to one of: flac|320|128."""
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
        provider,
        quality,
        artist,
        album,
        release_id,
        output_path,
    )

    if provider == "deemix":
        deezer_id = str(data.get("deezer_id", "")).strip() or None
        dcfg = _deemix_settings()

        if not deezer_id:
            if not (artist.strip() or album.strip()):
                return ({"error": "deezer_id or (artist+album) is required"}, 400)
            deezer_id = await deemix_provider.resolve_deezer_id_for_album(
                artist=artist,
                album=album,
                timeout_seconds=dcfg["timeout_seconds"],
            )
            if not deezer_id:
                return (
                    {"error": "Could not resolve Deezer release for deemix download"},
                    404,
                )

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
                bitrate=_deemix_bitrate_for_quality(quality) or "9",
            )
        )
        return (job, 202)

    if provider == "slskd":
        if not album.strip() and not artist.strip():
            return ({"error": "artist or album required"}, 400)

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
                artist=artist,
                album=album,
                timeout_seconds=min(20, wcfg["timeout_seconds"]),
                base_url=wcfg["base_url"],
            )
            if not match:
                return ({"error": "Could not resolve SquidWTF release"}, 404)
            squid_album_id = str(match.get("squid_album_id") or "").strip() or None
            if not squid_album_id:
                return ({"error": "SquidWTF album id missing in match"}, 502)

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
    """Search each provider once, then iterate quality priority to select best match.

    Phase 1 — probe: deemix (album ID + account tier), slskd (search + rank),
    squidwtf (album ID). Each provider queried at most once.
    Phase 2 — select: walk quality_priority; at the first tier where any provider
    can deliver, return the highest-scored candidate.

    `qualities`: caller-supplied ordered list (raw tokens, may include bare aliases
    like "flac" or "mp3"); if None, the config priority list is used.
    """
    artist = str(album_payload.get("artist", "")).strip()
    album = str(album_payload.get("album", "")).strip()

    if not artist and not album:
        log.warning("_find_best_match: no artist or album")
        return None

    # Build quality priority from caller list or config default.
    if qualities:
        quality_priority: list[str] = []
        for q in qualities:
            quality_priority.extend(_expand_quality_token(q))
    else:
        quality_priority = _auto_download_quality_priority()

    dcfg = _deemix_settings()
    scfg = _slskd_settings()
    wcfg = _squidwtf_settings()

    # ── Phase 1: probe each provider once ─────────────────────────────────

    deemix_id: str | None = str(album_payload.get("deezer_id", "")).strip() or None
    deemix_score: float = 1.0
    deemix_max_quality = "128"

    if "deemix" in providers and dcfg["base_url"]:
        try:
            aq = await deemix_provider.resolve_quality_from_arl(
                base_url=dcfg["base_url"],
                timeout_seconds=dcfg["timeout_seconds"],
                auth_header=dcfg["auth_header"],
                arl=dcfg["arl"],
            )
        except Exception as exc:
            log.warning("_find_best_match: deemix quality detection failed: %s", exc)
            aq = None
        deemix_max_quality = _deemix_available_quality(aq)

        if not deemix_id:
            for q_artist, q_album in _search_query_variants(artist, album):
                try:
                    m = await deemix_provider.resolve_deezer_match_for_album(
                        artist=q_artist,
                        album=q_album,
                        timeout_seconds=dcfg["timeout_seconds"],
                    )
                    if m:
                        deemix_id = m.get("deezer_id")
                        deemix_score = float(m.get("score") or 0.0)
                        break
                except Exception as exc:
                    log.debug("deemix match search failed: %s", exc)

    slskd_ranked: list[dict] = []
    if "slskd" in providers and scfg["base_url"]:
        try:
            candidates = await slskd_provider.search_album(
                base_url=scfg["base_url"],
                api_key=scfg["api_key"],
                artist=artist,
                album=album,
                timeout_seconds=scfg["timeout_seconds"],
            )
            slskd_ranked = slskd_provider.rank_candidates(candidates, album_hint=album)
        except Exception as exc:
            log.debug("slskd search failed: %s", exc)

    squid_id: str | None = str(album_payload.get("squid_album_id", "")).strip() or None
    if "squidwtf" in providers and wcfg["base_url"] and not squid_id:
        try:
            m = await squidwtf_provider.resolve_squidwtf_match_for_album(
                artist=artist,
                album=album,
                timeout_seconds=min(20, wcfg["timeout_seconds"]),
                base_url=wcfg["base_url"],
            )
            if m:
                squid_id = str(m.get("squid_album_id") or "").strip() or None
        except Exception as exc:
            log.debug("squidwtf search failed: %s", exc)

    # ── Phase 2: iterate quality priority ─────────────────────────────────

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
                    "provider": "squidwtf",
                    "quality": quality,
                    "squid_album_id": squid_id,
                    "squid_quality": squid_code,
                })
                results.append((1.0, payload))

        if results:
            best_score, best_payload = max(results, key=lambda x: x[0])
            log.info(
                "_find_best_match: selected provider=%s quality=%s score=%.2f",
                best_payload.get("provider"), quality, best_score,
            )
            return best_payload

    log.warning("_find_best_match: no match found for artist=%s album=%s", artist, album)
    return None


@discovery_bp.route("/quality-priority", methods=["GET"])
async def get_quality_priority():
    """Return the configured quality priority list for batch/auto downloads."""
    return jsonify({"quality_priority": _auto_download_quality_priority()})


@discovery_bp.route("/search/artists", methods=["GET"])
async def search_artists():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q is required"}), 400

    base_url = _musicbrainz_api_base_url()
    url = f"{base_url}/artist?query={quote(q)}&limit=15&fmt=json"
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
    artists = get_followed_artists()
    missing_map = get_missing_count_map()
    for a in artists:
        a["missing_count"] = missing_map.get(normalize_artist_key(a["name"]), 0)
    return jsonify(artists)


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
    invalidate_missing_cache_for_string(name)
    return jsonify({"ok": True})


@discovery_bp.route("/artists/<path:name>/status", methods=["GET"])
async def followed_artist_status(name: str):
    return jsonify({"name": name, "followed": is_followed(name)})


@discovery_bp.route("/download", methods=["POST"])
async def start_download():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

    payload, status = await _schedule_download_from_payload(data)
    return jsonify(payload), status


@discovery_bp.route("/download/batch", methods=["POST"])
async def start_download_batch():
    data = await request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "request body is required"}), 400

    providers_raw = data.get("providers", [])
    qualities_raw = data.get("qualities") or None  # None → use config priority

    providers_raw = providers_raw if isinstance(providers_raw, list) else []
    providers = [str(p).strip().casefold() for p in providers_raw]
    providers = [p for p in providers if p in ("deemix", "slskd", "squidwtf")]
    if not providers:
        providers = ["deemix", "slskd", "squidwtf"]

    # qualities: caller-supplied ordered priority list; None means use config default.
    # Bare tokens ("flac", "mp3") are expanded inside _find_best_match_across_providers.
    qualities: list[str] | None = None
    if isinstance(qualities_raw, list) and qualities_raw:
        qualities = [str(q).strip() for q in qualities_raw if str(q).strip()]
    
    albums = data.get("albums")
    if not isinstance(albums, list) or len(albums) == 0:
        return jsonify({"error": "albums must be a non-empty list"}), 400

    jobs: list[dict] = []
    errors: list[dict] = []
    for idx, album_payload in enumerate(albums):
        if not isinstance(album_payload, dict):
            errors.append({"index": idx, "error": "album payload must be an object"})
            continue

        # Search all providers with quality priority
        payload = await _find_best_match_across_providers(
            album_payload=album_payload,
            providers=providers,
            qualities=qualities,
        )
        
        if not payload:
            errors.append({
                "index": idx,
                "artist": str(album_payload.get("artist", "")),
                "album": str(album_payload.get("album", "")),
                "error": "No match found across selected providers and qualities",
                "status": 404,
            })
            continue

        job_or_error, status = await _schedule_download_from_payload(payload)
        if 200 <= status < 300:
            jobs.append(job_or_error)
        else:
            errors.append({
                "index": idx,
                "artist": str(payload.get("artist", "")),
                "album": str(payload.get("album", "")),
                "error": str(job_or_error.get("error", "Download scheduling failed")),
                "status": status,
            })

    return jsonify({
        "providers": providers,
        "qualities": qualities,
        "requested": len(albums),
        "queued": len(jobs),
        "failed": len(errors),
        "jobs": jobs,
        "errors": errors,
    }), 202 if jobs else 400


@discovery_bp.route("/download/options", methods=["POST"])
async def download_options():
    data = await request.get_json()
    if not data:
        return jsonify({"error": "request body is required"}), 400

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

        ranked = slskd_provider.rank_candidates(candidates, album_hint=album, expected_track_count=expected_track_count)
        log.info("slskd: %d candidates ranked", len(ranked))
        options = []
        for candidate in ranked[:20]:
            score = float(slskd_provider.score_candidate(candidate, album_hint=album, expected_track_count=expected_track_count))
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

        base_score = float(match.get("score") or 0.0)
        squid_album_id = match.get("squid_album_id")
        results = []
        for q_alias, q_code in [("flac:hires", "27"), ("flac:16", "6"), ("mp3:320", "5")]:
            quality_info = squidwtf_provider.quality_label_to_display(q_alias)
            results.append(
                _download_suggestion_summary(
                    provider="squidwtf",
                    score=base_score,
                    title=str(match.get("title") or album),
                    artist=str(match.get("artist") or artist),
                    details={
                        "squid_album_id": squid_album_id,
                        "trackCount": match.get("track_count"),
                        "quality": q_code,
                        "container": quality_info.get("container"),
                        "kbps": quality_info.get("kbps"),
                        "source": "qobuz",
                        "url": f"{base_url.rstrip('/')}/api/get-album?album_id={squid_album_id}",
                    },
                )
            )
        return results

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
    ranked = slskd_provider.rank_candidates(candidates, album_hint=album)
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
