"""Prowlarr (search) + qBittorrent (download) provider."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import aiohttp
from thefuzz import fuzz

from beets_flask.logger import log


def _norm_text(value: str) -> str:
    return (value or "").casefold().strip()


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


# Quality tier weights for scoring (higher = better).
_QUALITY_TIER: dict[str, float] = {
    "flac:24": 1.0,
    "flac:16": 0.85,
    "mp3:320": 0.6,
    "opus:320": 0.55,
    "mp3:256": 0.45,
    "opus:256": 0.4,
    "mp3:192": 0.3,
    "mp3:128": 0.15,
}

_FLAC_HIRES_RE = re.compile(
    r"\b(24\s*[-–]?\s*bit|24bit|hi[\s\-]?res|hires|highr|96\s*khz|192\s*khz|88\.?2\s*khz)\b",
    re.IGNORECASE,
)
_FLAC_RE = re.compile(r"\bFLAC\b", re.IGNORECASE)
_OPUS_RE = re.compile(r"\b(OPUS|OGG)\b", re.IGNORECASE)
_MP3_RE = re.compile(r"\bMP3\b", re.IGNORECASE)
_KBPS_RE = re.compile(r"\b(320|256|192|128|96|64)\s*(?:kbps|kb/s)?\b", re.IGNORECASE)


def _infer_quality(title: str) -> dict[str, Any]:
    """Infer audio quality from a torrent title string.

    Returns dict with keys: container, kbps, bit_depth, quality_token.
    """
    if _FLAC_RE.search(title):
        if _FLAC_HIRES_RE.search(title):
            return {"container": "FLAC", "kbps": None, "bit_depth": 24, "quality_token": "flac:24"}
        return {"container": "FLAC", "kbps": None, "bit_depth": 16, "quality_token": "flac:16"}

    kbps_match = _KBPS_RE.search(title)
    kbps = int(kbps_match.group(1)) if kbps_match else None

    if _OPUS_RE.search(title):
        token = f"opus:{kbps}" if kbps else "opus:320"
        return {"container": "OPUS", "kbps": kbps or 320, "bit_depth": None, "quality_token": token}

    if _MP3_RE.search(title) or kbps is not None:
        resolved_kbps = kbps or 128
        token = f"mp3:{resolved_kbps}"
        return {"container": "MP3", "kbps": resolved_kbps, "bit_depth": None, "quality_token": token}

    return {"container": "unknown", "kbps": None, "bit_depth": None, "quality_token": ""}


def score_candidate(candidate: dict, *, artist_hint: str, album_hint: str) -> float:
    """Score a Prowlarr candidate 0.0–1.0.

    Weights:
        60% title fuzzy match (token_sort_ratio vs "artist album")
        30% seeders (normalized, saturates at 50)
        10% quality tier
    """
    title = str(candidate.get("title") or "")
    seeders = _safe_int(candidate.get("seeders"), 0)
    quality_token = str(candidate.get("quality_token") or "")

    query = _norm_text(f"{artist_hint} {album_hint}")
    title_score = fuzz.token_sort_ratio(_norm_text(title), query) / 100.0

    seeder_score = min(seeders, 50) / 50.0

    tier_score = _QUALITY_TIER.get(quality_token, 0.1)

    return round(0.60 * title_score + 0.30 * seeder_score + 0.10 * tier_score, 4)


def rank_candidates(
    candidates: list[dict],
    *,
    artist_hint: str,
    album_hint: str,
) -> list[dict]:
    """Add 'score' to each candidate, sort descending, drop below 0.1."""
    scored = []
    for c in candidates:
        c = dict(c)
        c["score"] = score_candidate(c, artist_hint=artist_hint, album_hint=album_hint)
        scored.append(c)
    scored.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    return [c for c in scored if float(c.get("score", 0)) >= 0.1]


async def search_album(
    *,
    prowlarr_base_url: str,
    prowlarr_api_key: str,
    artist: str,
    album: str,
    categories: list[int] | None = None,
    timeout_seconds: float = 30,
) -> list[dict[str, Any]]:
    """Search Prowlarr for an album, returning a list of raw candidate dicts."""
    if categories is None:
        categories = [3000]

    query = f"{artist} {album}".strip()
    categories_str = ",".join(str(c) for c in categories)
    url = (
        f"{prowlarr_base_url.rstrip('/')}/api/v1/search"
        f"?query={quote(query)}&type=search&indexerIds=-2"
        f"&categories={categories_str}&apikey={prowlarr_api_key}"
    )

    log.info("prowlarr search url=%s", url)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("prowlarr search HTTP %s: %s", resp.status, body[:200])
                    return []
                raw: list[dict] = await resp.json()
    except Exception as exc:
        log.warning("prowlarr search failed: %s", exc)
        return []

    candidates: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        quality = _infer_quality(title)
        candidates.append({
            "provider": "prowlarr",
            "guid": str(item.get("guid") or ""),
            "title": title,
            "download_url": item.get("downloadUrl") or item.get("link") or None,
            "magnet_url": item.get("magnetUrl") or None,
            "seeders": _safe_int(item.get("seeders"), 0),
            "leechers": _safe_int(item.get("leechers"), 0),
            "size": _safe_int(item.get("size"), 0),
            "indexer": str(item.get("indexer") or ""),
            "info_url": item.get("infoUrl") or None,
            "container": quality["container"],
            "kbps": quality["kbps"],
            "bit_depth": quality["bit_depth"],
            "quality_token": quality["quality_token"],
        })

    log.info("prowlarr search query=%r found=%d", query, len(candidates))
    return candidates


async def enqueue_download(
    *,
    qbit_base_url: str,
    qbit_username: str,
    qbit_password: str,
    candidate: dict,
    output_path: str,
    timeout_seconds: float = 20,
) -> tuple[bool, str | None]:
    """Send a torrent to qBittorrent for download.

    Returns (True, None) on success, (False, error_reason) on failure.
    """
    base = qbit_base_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    torrent_url = candidate.get("magnet_url") or candidate.get("download_url")
    if not torrent_url:
        return False, "candidate has no magnet_url or download_url"

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Login
            login_resp = await session.post(
                f"{base}/api/v2/auth/login",
                data={"username": qbit_username, "password": qbit_password},
            )
            login_text = await login_resp.text()
            if login_text.strip() != "Ok.":
                log.warning("qbittorrent login failed: %s", login_text[:200])
                return False, f"qBittorrent login failed: {login_text.strip()[:100]}"

            # Add torrent
            add_resp = await session.post(
                f"{base}/api/v2/torrents/add",
                data={
                    "urls": torrent_url,
                    "savepath": output_path,
                    "category": "music",
                },
            )
            add_text = await add_resp.text()
            if add_resp.status == 200 and add_text.strip() == "Ok.":
                log.info(
                    "qbittorrent enqueue ok title=%r output=%s",
                    candidate.get("title"), output_path,
                )
                return True, add_text.strip()

            log.warning(
                "qbittorrent add failed status=%s body=%s",
                add_resp.status, add_text[:200],
            )
            return False, f"qBittorrent add failed ({add_resp.status}): {add_text.strip()[:100]}"

    except Exception as exc:
        log.exception("qbittorrent enqueue error")
        return False, str(exc)
