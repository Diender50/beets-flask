"""Artist routes."""

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from urllib.parse import quote, urlparse

import musicbrainzngs
import pandas as pd
from fastapi import APIRouter, HTTPException, Response

from beets_flask.config import get_config
from beets_flask.library_cache import (
    ARTISTS_CACHE_PREFIX,
    MISSING_CACHE_PREFIX,
    get_db_missing_cache,
    get_json_cache,
    get_missing_count_map,
    invalidate_artists_cache,
    invalidate_artists_list_cache,
    set_db_missing_cache,
    set_json_cache,
)
from beets_flask.logger import log
from beets_flask.server.dependencies import BeetsLib
from beets_flask.server.exceptions import NotFoundException

ARTIST_SEPARATORS: list[str] = get_config()["gui"]["library"][
    "artist_separators"
].as_str_seq()


def _split_pattern(separators: list[str]) -> str:
    return "|".join(map(re.escape, separators))


split_pattern_artists = _split_pattern(ARTIST_SEPARATORS)

ARTISTS_CACHE_TTL_SECONDS = 300
MISSING_CACHE_TTL_SECONDS = 3600
_MUSICBRAINZ_ID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


def _musicbrainz_api_base_url() -> str:
    try:
        return (
            str(
                get_config()["gui"]["discovery"]["musicbrainz"]["base_url"].get(
                    "https://musicbrainz.org/ws/2"
                )
            )
            .strip()
            .rstrip("/")
        )
    except Exception:
        return "https://musicbrainz.org/ws/2"


def _configure_musicbrainz_client() -> None:
    base_url = _musicbrainz_api_base_url()
    parsed = urlparse(base_url)

    hostname = parsed.netloc or parsed.path
    use_https = parsed.scheme.casefold() != "http"

    if not hostname:
        hostname = "musicbrainz.org"
        use_https = True

    musicbrainzngs.set_hostname(hostname, use_https=use_https)


def _artists_cache_key(artist_name: str | None) -> str:
    return f"{ARTISTS_CACHE_PREFIX}{artist_name or '__all__'}"


def _missing_cache_key(artist_name: str) -> str:
    return f"{MISSING_CACHE_PREFIX}{artist_name}"


def _normalize_artist_name(artist_name: str) -> str:
    return artist_name.strip().casefold()


def _parse_missing_album_line(line: str) -> dict[str, str | int | None] | None:
    line = line.strip()
    if not line:
        return None

    if " - " in line:
        _, album = line.split(" - ", 1)
    else:
        album = line

    return {
        "album": album.strip(),
        "year": None,
        "mb_releasegroupid": None,
    }


def _extract_release_group_year(first_release_date: str | None) -> int | None:
    if not first_release_date:
        return None

    match = re.match(r"^(\d{4})", first_release_date)
    if not match:
        return None

    return int(match.group(1))


def _artist_names_from_item(item) -> list[str]:
    artists = getattr(item, "artists", None)
    if artists:
        return [str(artist).strip() for artist in artists if str(artist).strip()]

    artist = getattr(item, "artist", None)
    if not artist:
        return []

    if ARTIST_SEPARATORS:
        return [
            artist_name.strip()
            for artist_name in re.split(split_pattern_artists, str(artist))
            if artist_name.strip()
        ]

    return [str(artist).strip()]


def _albumartist_names_from_album(album) -> list[str]:
    albumartists = getattr(album, "albumartists", None)
    if albumartists:
        return [str(artist).strip() for artist in albumartists if str(artist).strip()]

    albumartist = getattr(album, "albumartist", None)
    if not albumartist:
        return []

    if ARTIST_SEPARATORS:
        return [
            artist_name.strip()
            for artist_name in re.split(split_pattern_artists, str(albumartist))
            if artist_name.strip()
        ]

    return [str(albumartist).strip()]


def _extract_valid_mbids(raw: object) -> list[str]:
    if raw is None:
        return []

    text = str(raw)
    return [match.group(0).lower() for match in _MUSICBRAINZ_ID_RE.finditer(text)]


def _resolve_lib(lib=None):
    if lib is None:
        raise ValueError("lib must be passed explicitly")
    return lib


def _find_artist_mbids(artist_name: str, lib=None) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    mbids: set[str] = set()
    beets_lib = _resolve_lib(lib)

    with beets_lib.transaction() as tx:
        rows = tx.query("SELECT id FROM items WHERE instr(artist, ?) > 0", (artist_name,))

    for row in rows:
        item = beets_lib.get_item(row[0])
        if item is None:
            continue

        artist_names = _artist_names_from_item(item)
        artist_mbids = list(getattr(item, "mb_artistids", []) or [])
        if len(artist_names) != len(artist_mbids):
            continue

        for item_artist_name, mbid in zip(artist_names, artist_mbids, strict=False):
            if _normalize_artist_name(item_artist_name) != normalized_artist_name:
                continue
            for parsed_mbid in _extract_valid_mbids(mbid):
                mbids.add(parsed_mbid)

    return mbids


def _owned_release_group_ids(artist_name: str, lib=None) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    release_group_ids: set[str] = set()
    beets_lib = _resolve_lib(lib)

    with beets_lib.transaction() as tx:
        rows = tx.query(
            "SELECT id FROM albums WHERE instr(albumartist, ?) > 0",
            (artist_name,),
        )

    for row in rows:
        album = beets_lib.get_album(row[0])
        if album is None:
            continue

        if normalized_artist_name not in {
            _normalize_artist_name(name) for name in _albumartist_names_from_album(album)
        }:
            continue

        release_group_id = getattr(album, "mb_releasegroupid", None)

        if release_group_id:
            release_group_ids.add(str(release_group_id))

    return release_group_ids


_MB_RELEASE_TYPE_MAP: dict[str, str] = {
    "Album": "album",
    "EP": "ep",
    "Single": "single",
    "Broadcast": "other",
    "Other": "other",
}

_MB_SECONDARY_TYPE_MAP: dict[str, str] = {
    "Live": "live",
    "Compilation": "compilation",
    "Remix": "remix",
    "Soundtrack": "soundtrack",
}


def _release_type_from_mb(release_group: dict) -> str:
    secondary = release_group.get("secondary-type-list", [])
    for sec_type, mapped in _MB_SECONDARY_TYPE_MAP.items():
        if sec_type in secondary:
            return mapped
    primary = release_group.get("primary-type", "")
    return _MB_RELEASE_TYPE_MAP.get(primary, "album")


def _normalize_for_dedup(title: str) -> str:
    """Normalize an album title for cross-source deduplication.

    Handles Unicode punctuation variants (en-dash, curly apostrophe, …),
    strips common edition/remaster/bonus parenthetical suffixes so that
    "Névrose" and "Névrose (Deluxe Edition)" are treated as the same release.
    """
    # NFKC decomposes compatibility forms (fullwidth chars, ligatures, …)
    t = unicodedata.normalize("NFKC", title).casefold().strip()

    # Normalize all hyphen/dash variants → plain hyphen-minus U+002D
    # Covers: HYPHEN ‐, NON-BREAKING HYPHEN ‑, FIGURE DASH ‒, EN DASH –,
    #         EM DASH —, MINUS SIGN −, SMALL HYPHEN-MINUS ﹣, FULLWIDTH －
    t = re.sub(r"[‐‑‒–—−﹘﹣－]", "-", t)

    # Strip apostrophe/quote variants entirely for dedup robustness:
    # "t'aime" == "taime" regardless of which Unicode apostrophe the source uses.
    # \uXXXX escapes are resolved by Python at parse time → encoding-safe.
    t = re.sub(
        "['`´ʹʻʼʽ''‚‛′‵＇]",
        "",
        t,
    )

    # Normalize conjunction variants → & so "A & B", "A and B", "A et B" all match.
    t = re.sub(r"\s+(?:and|et)\s+", " & ", t)
    t = re.sub(r"\s*&\s*", " & ", t)

    # Remove parenthetical / bracketed edition suffixes
    t = re.sub(
        r"\s*[\(\[][^\)\]]*"
        r"(deluxe|edition|remaster(?:ed)?|re-?master(?:ed)?|bonus"
        r"|explicit|clean|expanded|anniversary|special|standard|extended"
        r"|version|vol\.?|volume)[^\)\]]*[\)\]]",
        "",
        t,
        flags=re.IGNORECASE,
    )

    # Collapse & trim trailing whitespace/punctuation
    return re.sub(r"[\s\-_:]+$", "", t).strip()


def _is_prefix_single_of_owned_title(
    candidate_title_dedup: str,
    owned_titles_dedup: set[str],
) -> bool:
    """Heuristic: Deezer single title is strict prefix of an owned album title.

    Example: single "ten" while owned album "ten days".
    """
    t = candidate_title_dedup.strip()
    if not t or " " in t:
        return False

    for owned in owned_titles_dedup:
        if owned.startswith(f"{t} "):
            return True
    return False


def _owned_album_titles_normalized(artist_name: str, lib=None) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    titles: set[str] = set()
    beets_lib = _resolve_lib(lib)

    with beets_lib.transaction() as tx:
        rows = tx.query(
            "SELECT id FROM albums WHERE instr(albumartist, ?) > 0",
            (artist_name,),
        )

    for row in rows:
        album = beets_lib.get_album(row[0])
        if album is None:
            continue
        if normalized_artist_name not in {
            _normalize_artist_name(name) for name in _albumartist_names_from_album(album)
        }:
            continue
        album_title = getattr(album, "album", None)
        if album_title:

            titles.add(_normalize_for_dedup(str(album_title)))

    return titles


def _search_artist_mbid_from_mb(artist_name: str) -> set[str]:
    """Search MusicBrainz by name and return MBID(s) for the best-matching artist."""
    try:
        result = musicbrainzngs.search_artists(artist=artist_name, limit=5)
        normalized = _normalize_artist_name(artist_name)
        for artist in result.get("artist-list", []):
            if _normalize_artist_name(artist.get("name", "")) == normalized:
                mbids = _extract_valid_mbids(artist.get("id"))
                if mbids:
                    return set(mbids)
        # No exact match — take highest-scored result if score >= 90
        for artist in result.get("artist-list", []):
            score = int(artist.get("ext:score", 0) or 0)
            if score >= 90:
                mbids = _extract_valid_mbids(artist.get("id"))
                if mbids:
                    return set(mbids)
    except Exception:
        pass
    return set()


def _safe_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _release_date_key(date_value: str | None) -> tuple[int, int, int]:
    if not date_value:
        return (9999, 12, 31)

    parts = str(date_value).split("-")
    year = _safe_int(parts[0]) if len(parts) >= 1 else None
    month = _safe_int(parts[1]) if len(parts) >= 2 else None
    day = _safe_int(parts[2]) if len(parts) >= 3 else None
    return (
        year if year is not None else 9999,
        month if month is not None else 12,
        day if day is not None else 31,
    )


_PREFERRED_COUNTRY_ORDER = {
    "XW": 0,  # Worldwide
    "US": 1,
    "GB": 2,
    "FR": 3,
    "DE": 4,
    "CA": 5,
    "JP": 6,
    "BE": 7,
}


def _release_track_count_from_summary(release: dict) -> int | None:
    medium_track_count = _safe_int(release.get("medium-track-count"))
    if medium_track_count is not None:
        return medium_track_count

    total = 0
    found = False
    for medium in release.get("medium-list", []):
        track_count = _safe_int(medium.get("track-count"))
        if track_count is None:
            continue
        total += track_count
        found = True

    if found:
        return total
    return None


def _pick_best_release_for_group(release_group_id: str) -> dict | None:
    rg = musicbrainzngs.get_release_group_by_id(release_group_id, includes=["releases"])
    releases = rg.get("release-group", {}).get("release-list", [])
    if not releases:
        return None

    def sort_key(release: dict) -> tuple:
        status_rank = 0 if str(release.get("status", "")).casefold() == "official" else 1
        country_rank = _PREFERRED_COUNTRY_ORDER.get(str(release.get("country", "")), 99)
        disambiguation_rank = 1 if str(release.get("disambiguation", "")).strip() else 0
        date_rank = _release_date_key(release.get("date"))
        track_count = _release_track_count_from_summary(release)
        has_track_count_rank = 0 if track_count is not None else 1
        track_count_rank = -(track_count or 0)
        return (
            status_rank,
            country_rank,
            disambiguation_rank,
            date_rank,
            has_track_count_rank,
            track_count_rank,
            str(release.get("id", "")),
        )

    return min(releases, key=sort_key)


def _release_track_count_from_detail(release: dict) -> int | None:
    total = 0
    found = False
    for medium in release.get("medium-list", []):
        track_count = _safe_int(medium.get("track-count"))
        if track_count is not None:
            total += track_count
            found = True
            continue

        track_list = medium.get("track-list", [])
        if track_list:
            total += len(track_list)
            found = True

    if found:
        return total
    return None


def _best_release_track_count_for_group(release_group_id: str) -> int | None:
    _configure_musicbrainz_client()
    best_release = _pick_best_release_for_group(release_group_id)
    if best_release is None:
        return None

    track_count = _release_track_count_from_summary(best_release)
    if track_count is not None:
        return track_count

    best_release_id = best_release.get("id")
    if not best_release_id:
        return None

    release = musicbrainzngs.get_release_by_id(best_release_id, includes=["recordings"])
    return _release_track_count_from_detail(release.get("release", {}))


def _best_release_tracks_for_group(release_group_id: str) -> list[dict[str, str | int | None]]:
    _configure_musicbrainz_client()
    best_release = _pick_best_release_for_group(release_group_id)
    if best_release is None:
        return []

    best_release_id = best_release.get("id")
    if not best_release_id:
        return []

    release = musicbrainzngs.get_release_by_id(best_release_id, includes=["recordings"])
    tracks: list[dict[str, str | int | None]] = []
    for medium in release.get("release", {}).get("medium-list", []):
        for track in medium.get("track-list", []):
            recording = track.get("recording", {})
            length_ms = _safe_int(recording.get("length"))
            tracks.append({
                "title": recording.get("title") or track.get("title", ""),
                "duration": length_ms // 1000 if length_ms else None,
                "track_position": _safe_int(track.get("position") or track.get("number")),
            })
    return tracks


def _missing_albums_from_musicbrainz(
    artist_name: str,
    lib=None,
) -> list[dict[str, str | int | None]]:
    _configure_musicbrainz_client()
    artist_mbids = _find_artist_mbids(artist_name, lib=lib)
    if not artist_mbids:
        # Artist not in beets library — search MB by name
        artist_mbids = _search_artist_mbid_from_mb(artist_name)
    if not artist_mbids:
        return []

    log.info(
        "missing_albums musicbrainz mbids artist=%s count=%s mbids=%s",
        artist_name,
        len(artist_mbids),
        sorted(artist_mbids),
    )

    owned_release_group_ids = _owned_release_group_ids(artist_name, lib=lib)
    owned_titles = _owned_album_titles_normalized(artist_name, lib=lib)
    missing_by_release_group: dict[str, dict[str, str | int | None]] = {}
    had_successful_lookup = False

    for artist_mbid in sorted(artist_mbids):
        try:
            response = musicbrainzngs.browse_release_groups(
                artist=artist_mbid, includes=["artist-credits"]
            )
            had_successful_lookup = True
        except Exception as exc:
            log.warning(
                "missing_albums skip musicbrainz artist id artist=%s mbid=%s error_type=%s error=%s",
                artist_name,
                artist_mbid,
                type(exc).__name__,
                exc,
            )
            continue

        for release_group in response.get("release-group-list", []):
            release_group_id = release_group.get("id")
            if not release_group_id or release_group_id in owned_release_group_ids:
                continue
            # Skip release groups where this artist is only a guest/featured artist.
            # The first entry in artist-credit is the primary credited artist.
            artist_credit = release_group.get("artist-credit") or []
            first_credit = artist_credit[0] if artist_credit else None
            if first_credit:
                first_mbid = (first_credit.get("artist") or {}).get("id")
                if first_mbid and first_mbid not in artist_mbids:
                    continue
            # Also filter by title: catches imported albums whose mb_releasegroupid
            # doesn't match (e.g. beets set a different release ID, or no ID at all)
            title_key = _normalize_for_dedup(release_group.get("title", ""))
            if title_key in owned_titles:
                continue

            missing_by_release_group[release_group_id] = {
                "album": release_group.get("title", ""),
                "year": _extract_release_group_year(
                    release_group.get("first-release-date")
                ),
                "mb_releasegroupid": release_group_id,
                "release_type": _release_type_from_mb(release_group),
                "cover_url": None,
                "track_count": None,
            }

    if not had_successful_lookup:
        fallback_mbids = _search_artist_mbid_from_mb(artist_name)
        extra_mbids = sorted(fallback_mbids - artist_mbids)
        if extra_mbids:
            log.info(
                "missing_albums musicbrainz fallback_mbids artist=%s mbids=%s",
                artist_name,
                extra_mbids,
            )
        for artist_mbid in extra_mbids:
            try:
                response = musicbrainzngs.browse_release_groups(
                    artist=artist_mbid, includes=["artist-credits"]
                )
            except Exception:
                continue

            for release_group in response.get("release-group-list", []):
                release_group_id = release_group.get("id")
                if not release_group_id or release_group_id in owned_release_group_ids:
                    continue
                artist_credit = release_group.get("artist-credit") or []
                first_credit = artist_credit[0] if artist_credit else None
                if first_credit:
                    first_mbid = (first_credit.get("artist") or {}).get("id")
                    if first_mbid and first_mbid not in artist_mbids:
                        continue
                title_key = _normalize_for_dedup(release_group.get("title", ""))
                if title_key in owned_titles:
                    continue

                missing_by_release_group[release_group_id] = {
                    "album": release_group.get("title", ""),
                    "year": _extract_release_group_year(
                        release_group.get("first-release-date")
                    ),
                    "mb_releasegroupid": release_group_id,
                    "release_type": _release_type_from_mb(release_group),
                    "cover_url": None,
                    "track_count": None,
                }

    return list(missing_by_release_group.values())


def _missing_albums_from_deezer(
    artist_name: str,
    owned_titles_dedup: set[str],
) -> dict[str, dict[str, str | int | None]]:
    """Query the Deezer public API for albums not already owned, keyed by dedup title.

    Returns a dict keyed by normalised title so the caller can merge with MusicBrainz
    results. Within Deezer, duplicate editions of the same album (e.g. Deluxe, Explicit)
    are collapsed to the first-seen entry (first-wins keeps the canonical edition that
    Deezer returns first).  The ``mb_releasegroupid`` field is intentionally absent here;
    the caller sets it appropriately depending on whether a matching MB entry exists.
    """
    try:
        search_url = (
            "https://api.deezer.com/search/artist?q="
            + urllib.parse.quote(artist_name)
            + "&limit=5"
        )
        with urllib.request.urlopen(search_url, timeout=8) as req:  # noqa: S310
            search_data = json.loads(req.read())

        artist_id: int | None = None
        for candidate in search_data.get("data", []):
            if _normalize_artist_name(candidate.get("name", "")) == _normalize_artist_name(artist_name):
                artist_id = candidate["id"]
                break

        if not artist_id:
            return {}

        albums_url = f"https://api.deezer.com/artist/{artist_id}/albums?limit=200"
        with urllib.request.urlopen(albums_url, timeout=8) as req:  # noqa: S310
            albums_data = json.loads(req.read())

        # Keyed by dedup_key — first-wins deduplication across Deezer editions.
        by_dedup_key: dict[str, dict[str, str | int | None]] = {}
        for album in albums_data.get("data", []):
            title = album.get("title", "")
            dedup_key = _normalize_for_dedup(title)
            if dedup_key in owned_titles_dedup:
                continue

            record_type = str(album.get("record_type", "album"))
            if record_type.casefold() == "single" and _is_prefix_single_of_owned_title(
                dedup_key,
                owned_titles_dedup,
            ):
                continue

            # First-wins: skip later Deezer editions of an already-seen canonical title.
            if dedup_key in by_dedup_key:
                continue

            year_str = str(album.get("release_date", "") or "")
            year: int | None = int(year_str[:4]) if len(year_str) >= 4 else None
            deezer_id = album.get("id")

            # Fetch individual album to verify main artist and get nb_tracks.
            # /artist/{id}/albums also returns albums where the artist is only a
            # contributor (feat.), so we skip those by checking album_detail["artist"]["id"].
            track_count: int | None = None
            if deezer_id:
                try:
                    album_url = f"https://api.deezer.com/album/{deezer_id}"
                    with urllib.request.urlopen(album_url, timeout=5) as req:  # noqa: S310
                        album_detail = json.loads(req.read())
                    main_artist_id = (album_detail.get("artist") or {}).get("id")
                    if main_artist_id and int(main_artist_id) != artist_id:
                        continue
                    track_count = album_detail.get("nb_tracks")
                except Exception:
                    pass

            by_dedup_key[dedup_key] = {
                "album": title,
                "year": year,
                "deezer_id": deezer_id,
                "release_type": record_type,
                "cover_url": album.get("cover_medium") or album.get("cover") or None,
                "track_count": track_count,
            }
        return by_dedup_key

    except Exception:
        return {}


def _missing_albums_from_sources(
    artist_name: str,
    lib=None,
) -> list[dict[str, str | int | None]]:
    """Return missing albums merged from MusicBrainz and Deezer, sorted by year descending.

    Merging strategy:
    - MB albums whose normalised title matches a Deezer album are enriched with
      ``deezer_id`` (and ``cover_url`` / ``track_count`` when MB lacks them).
    - Deezer albums with no MB counterpart become standalone entries carrying
      ``mb_releasegroupid = "deezer:<id>"`` for backward-compat with the download flow.
    - Deezer editions of the same album (Deluxe, Explicit, …) are collapsed to one
      entry before the merge step.
    """
    mb_missing = _missing_albums_from_musicbrainz(artist_name, lib=lib)
    owned_titles = _owned_album_titles_normalized(artist_name, lib=lib)

    deezer_by_key = _missing_albums_from_deezer(artist_name, owned_titles)

    # Enrich MB entries with Deezer data when title matches; track which Deezer
    # entries were consumed so we can emit the remainder as standalone rows.
    consumed_deezer_keys: set[str] = set()
    enriched_mb: list[dict[str, str | int | None]] = []
    for m in mb_missing:
        dk = _normalize_for_dedup(str(m["album"]))
        entry = dict(m)
        deezer_match = deezer_by_key.get(dk)
        if deezer_match:
            consumed_deezer_keys.add(dk)
            entry["deezer_id"] = deezer_match["deezer_id"]
            if not entry.get("cover_url"):
                entry["cover_url"] = deezer_match.get("cover_url")
            if not entry.get("track_count"):
                entry["track_count"] = deezer_match.get("track_count")
        enriched_mb.append(entry)

    # Deezer-only entries: keep backward-compat mb_releasegroupid scheme.
    deezer_exclusive: list[dict[str, str | int | None]] = []
    for dk, deezer in deezer_by_key.items():
        if dk in consumed_deezer_keys:
            continue
        deezer_id = deezer.get("deezer_id")
        deezer_exclusive.append({
            "album": deezer["album"],
            "year": deezer.get("year"),
            "mb_releasegroupid": f"deezer:{deezer_id}" if deezer_id else None,
            "release_type": deezer.get("release_type"),
            "cover_url": deezer.get("cover_url"),
            "track_count": deezer.get("track_count"),
        })

    all_missing = enriched_mb + deezer_exclusive
    return sorted(
        all_missing,
        key=lambda a: (
            a["year"] is None,
            -(a["year"] or 0),
            str(a["album"]).casefold(),
        ),
    )


def recompute_missing_cache_for_artist(artist_name: str, lib=None) -> list[dict[str, str | int | None]]:
    """Compute and persist missing albums for one artist (Redis + DB)."""
    missing = _missing_albums_from_sources(artist_name, lib=lib)
    payload = pd.DataFrame(missing).to_json(orient="records")
    cache_key = _missing_cache_key(artist_name)
    set_json_cache(cache_key, payload, MISSING_CACHE_TTL_SECONDS)
    set_db_missing_cache(artist_name, payload)
    return missing


def _clean_cached_missing_payload(
    artist_name: str,
    payload: str,
    lib=None,
) -> tuple[str, bool]:
    """Drop stale cached missing albums that are now owned in library."""
    try:
        rows = json.loads(payload or "[]")
    except Exception:
        return payload, False

    if not isinstance(rows, list):
        return payload, False

    owned_titles = _owned_album_titles_normalized(artist_name, lib=lib)
    if not owned_titles:
        return payload, False

    cleaned = [
        row
        for row in rows
        if _normalize_for_dedup(str((row or {}).get("album", ""))) not in owned_titles
    ]
    changed = len(cleaned) != len(rows)
    if not changed:
        return payload, False

    cleaned_payload = pd.DataFrame(cleaned).to_json(orient="records")
    return cleaned_payload, True


def _all_library_artist_names(lib=None) -> list[str]:
    """Return deduplicated artist names for full missing-albums cache warmup."""
    artists_albums = get_artists_pandas("albums", lib=lib)
    artists_items = get_artists_pandas("items", lib=lib)
    names = {
        str(name).strip()
        for name in [*artists_albums["artist"].tolist(), *artists_items["artist"].tolist()]
        if str(name).strip()
    }
    return sorted(names, key=lambda n: n.casefold())


def _cached_missing_artist_names() -> set[str]:
    """Return artist names currently present in the persistent missing cache table."""
    try:
        from beets_flask.database.models.states import MissingAlbumCacheInDb
        from beets_flask.database.setup import session_factory

        session = session_factory()
        try:
            rows = session.query(MissingAlbumCacheInDb.artist_name).all()
            return {str(row[0]).strip() for row in rows if row and str(row[0]).strip()}
        finally:
            session.close()
    except Exception as exc:
        log.warning("Could not read missing cache table: %s", exc)
        return set()


def ensure_missing_cache_warmed_for_all_artists(
    *,
    lib=None,
    force_recompute: bool = False,
) -> dict[str, int | bool]:
    """Ensure all library artists have a persistent missing-albums cache entry.

    If ``force_recompute`` is False, only artists missing from the DB cache table are
    computed. If True, every artist is recomputed.
    """
    artist_names = _all_library_artist_names(lib=lib)
    cached_names = _cached_missing_artist_names()

    if force_recompute:
        target_names = artist_names
    else:
        target_names = [name for name in artist_names if name not in cached_names]

    warmed = 0
    failed = 0
    for artist_name in target_names:
        try:
            recompute_missing_cache_for_artist(artist_name, lib=lib)
            warmed += 1
        except Exception as exc:  # pragma: no cover
            failed += 1
            log.warning("Failed warming missing cache for artist=%s: %s", artist_name, exc)

    return {
        "ok": failed == 0,
        "artists_total": len(artist_names),
        "artists_cached_before": len(cached_names & set(artist_names)),
        "artists_warmed": warmed,
        "artists_failed": failed,
    }


def _missing_count_by_artist_name() -> dict[str, int]:
    return get_missing_count_map()


def get_artists_pandas(
    table: str,
    artist: str | None = None,
    include_size: bool = False,
    lib=None,
) -> pd.DataFrame:
    """Get all artists from the database using pandas.

    Returns
    -------
        DataFrame with columns ['artist', 'count', 'last_added', 'first_added', ('total_size' if include_size)]
    """
    if table == "items":
        if include_size:
            # Beets has no 'size' column; estimate bytes from length (seconds) * bitrate (bps) / 8
            query = """
                SELECT
                    artist,
                    added,
                    CAST(length * bitrate / 8 AS INTEGER) AS estimated_size
                FROM
                    items
            """
        else:
            query = """
                SELECT
                    artist,
                    added
                FROM
                    items
            """
    elif table == "albums":
        query = """
            SELECT
                albumartist AS artist,
                added

            FROM
                albums
        """
    else:
        raise ValueError(f"Invalid table name: {table}. Must be 'items' or 'albums'.")

    # Split the artist string by the specified separators
    artists: list[str] | None
    if len(ARTIST_SEPARATORS) > 0 and artist is not None:
        artists = [a.strip() for a in re.split(split_pattern_artists, artist)]
    elif artist is not None:
        artists = [artist.strip()]
    else:
        artists = None

    if artists is not None:
        # If an artist is specified, filter the query
        for i, a in enumerate(artists):
            if i == 0:
                query += f" WHERE instr(artist, ?) > 0"
            else:
                query += f" AND instr(artist, ?) > 0"

    beets_lib = _resolve_lib(lib)
    with beets_lib.transaction() as tx:
        rows = tx.query(query, artists) if artists else tx.query(query)

    # Read from the database
    if include_size and table == "items":
        df = pd.DataFrame(rows, columns=["artist", "added", "estimated_size"])
    else:
        df = pd.DataFrame(rows, columns=["artist", "added"])

    # Split artist strings into lists and explode into separate rows
    if len(ARTIST_SEPARATORS) > 0:
        df["artist"] = df["artist"].str.split(split_pattern_artists)
        df = df.explode("artist")

    # Strip whitespace
    df["artist"] = df["artist"].str.strip()
    df["added"] = df["added"] * 1000

    # Group by artist and aggregate
    if include_size and table == "items":
        result = (
            df.groupby("artist")
            .agg(
                count=("artist", "size"),
                last_added=("added", "max"),
                first_added=("added", "min"),
                total_size=("estimated_size", "sum"),
            )
            .reset_index()
        )
    else:
        result = (
            df.groupby("artist")
            .agg(
                count=("artist", "size"),
                last_added=("added", "max"),
                first_added=("added", "min"),
            )
            .reset_index()
        )

    if artists is not None:
        # If an artist is specified, filter the result (respect the separator and resolve as or)
        result = result[
            result["artist"].str.contains(
                _split_pattern(artists), case=False, regex=True
            )
        ]
        # Overwrite if there are multiple artists (i.e. joined by a separator)
        if len(artists) > 1 and not result.empty:
            result["artist"] = artist

    return result

router = APIRouter(tags=["library"])


# NOTE: specific routes (with literal path suffixes) registered BEFORE
# the wildcard {artist_name:path} routes to avoid greedy matching.


@router.post("/artists/missing/cache/warm-all")
async def warm_all_missing_albums_cache(lib: BeetsLib, force: bool = False) -> dict:
    result = ensure_missing_cache_warmed_for_all_artists(lib=lib, force_recompute=force)
    return result


@router.post("/artists/cache/refresh")
async def refresh_artists_cache() -> dict:
    cleared = invalidate_artists_cache()
    return {"ok": True, "cleared": cleared}


@router.get("/missing-album-tracks")
async def missing_album_tracks(id: str = "") -> list:
    if not id:
        raise HTTPException(status_code=400, detail="id is required")

    if id.startswith("deezer:"):
        deezer_id = id[7:]
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"https://api.deezer.com/album/{deezer_id}/tracks", timeout=8
            ) as req:
                data = json.loads(req.read())
            return [
                {
                    "title": t.get("title", ""),
                    "duration": t.get("duration"),
                    "track_position": t.get("track_position"),
                }
                for t in data.get("data", [])
            ]
        except Exception:
            return []
    else:
        try:
            return _best_release_tracks_for_group(id)
        except Exception:
            return []


@router.get("/artists/{artist_name:path}/missing")
async def missing_albums_by_artist(artist_name: str, lib: BeetsLib, refresh: bool = False) -> Response:
    cache_key = _missing_cache_key(artist_name)
    log.info("missing_albums request artist=%s refresh=%s", artist_name, refresh)

    if not refresh:
        cached = get_json_cache(cache_key)
        if cached is not None:
            cached, changed = _clean_cached_missing_payload(artist_name, cached, lib=lib)
            if changed:
                set_json_cache(cache_key, cached, MISSING_CACHE_TTL_SECONDS)
            set_db_missing_cache(artist_name, cached)
            log.info("missing_albums redis_hit artist=%s", artist_name)
            return Response(content=cached, media_type="application/json")

        log.info("missing_albums redis_miss artist=%s", artist_name)
        db_cached = get_db_missing_cache(artist_name)
        if db_cached is not None:
            db_cached, changed = _clean_cached_missing_payload(artist_name, db_cached, lib=lib)
            log.info("missing_albums db_hit artist=%s", artist_name)
            set_json_cache(cache_key, db_cached, MISSING_CACHE_TTL_SECONDS)
            if changed:
                set_db_missing_cache(artist_name, db_cached)
            return Response(content=db_cached, media_type="application/json")
        log.info("missing_albums db_miss artist=%s", artist_name)
    else:
        log.info("missing_albums force_refresh artist=%s", artist_name)

    invalidate_artists_list_cache()
    try:
        missing = recompute_missing_cache_for_artist(artist_name, lib=lib)
    except musicbrainzngs.musicbrainz.MusicBrainzError as exc:
        log.warning("missing_albums musicbrainz_error artist=%s error=%s", artist_name, exc)
        return Response(content="[]", media_type="application/json")

    payload = pd.DataFrame(missing).to_json(orient="records")
    log.info("missing_albums computed artist=%s count=%s", artist_name, len(missing))
    return Response(content=payload, media_type="application/json")


@router.get("/artists/{artist_name:path}")
async def artist_by_name(artist_name: str, lib: BeetsLib) -> Response:
    return await _get_artists(artist_name, lib)


@router.get("/artists")
async def all_artists(lib: BeetsLib) -> Response:
    return await _get_artists(None, lib)


async def _get_artists(artist_name: str | None, lib) -> Response:
    import unicodedata

    from beets_flask.library_cache import get_missing_count_map

    # Trailing slash in URL causes {artist_name:path} to capture "" — treat as None (all artists).
    if not artist_name:
        artist_name = None

    cache_key = _artists_cache_key(artist_name)
    cached = get_json_cache(cache_key)
    if cached is not None:
        return Response(content=cached, media_type="application/json")

    artists_albums = (
        get_artists_pandas("albums", artist_name, lib=lib)
        .rename(columns={"count": "album_count", "last_added": "last_album_added", "first_added": "first_album_added"})
        .set_index("artist")
    )
    artists_items = (
        get_artists_pandas("items", artist_name, include_size=True, lib=lib)
        .rename(columns={"count": "item_count", "last_added": "last_item_added", "first_added": "first_item_added"})
        .set_index("artist")
    )

    artists = artists_albums.join(artists_items, how="outer").reset_index()
    artists["album_count"] = artists["album_count"].fillna(0).astype(int)
    artists["item_count"] = artists["item_count"].fillna(0).astype(int)
    artists["total_size"] = artists["total_size"].fillna(0).astype(int)

    missing_count_map = get_missing_count_map()
    artists["missing_count"] = (
        artists["artist"]
        .apply(lambda n: missing_count_map.get(unicodedata.normalize("NFC", str(n)).strip(), 0))
        .fillna(0)
        .astype(int)
    )

    if artist_name is not None:
        if artists.empty:
            from beets_flask.discovery.followed_artists import is_followed

            if is_followed(artist_name):
                stub = {
                    "artist": artist_name,
                    "album_count": 0,
                    "item_count": 0,
                    "total_size": 0,
                    "missing_count": 0,
                    "followed": True,
                }
                return Response(content=json.dumps(stub), media_type="application/json")
            raise NotFoundException(f"Artist '{artist_name}' not found.")

        payload = artists.iloc[0].to_json()
        set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
        return Response(content=payload, media_type="application/json")

    payload = artists.to_json(orient="records")
    set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
    return Response(content=payload, media_type="application/json")
