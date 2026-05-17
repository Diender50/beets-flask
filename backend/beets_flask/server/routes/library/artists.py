"""Artists endpoint.

Split artists by separators, and do some basic aggregation.
"""

import json
import re
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

import musicbrainzngs
import pandas as pd
from quart import Blueprint, Response, g, jsonify, request

from beets_flask.config import get_config
from beets_flask.library_cache import (
    ARTISTS_CACHE_PREFIX,
    MISSING_CACHE_PREFIX,
    get_json_cache,
    invalidate_artists_cache,
    set_json_cache,
)
from beets_flask.server.exceptions import NotFoundException

artists_bp = Blueprint("artists", __name__)

if TYPE_CHECKING:
    # For type hinting the global g object
    from . import g

# TODOs:
# Currently artist_sort is completely ignored. Im not even sure what it is supposed to do.
# Also artistids are not used, but they are in the database.

# Note: I wanted to use polars first but it does not support alpine images yet, so we use pandas instead.


ARTIST_SEPARATORS: list[str] = get_config()["gui"]["library"][
    "artist_separators"
].as_str_seq()


def _split_pattern(separators: list[str]) -> str:
    return "|".join(map(re.escape, separators))


split_pattern_artists = _split_pattern(ARTIST_SEPARATORS)

ARTISTS_CACHE_TTL_SECONDS = 300
MISSING_CACHE_TTL_SECONDS = 600


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


def _find_artist_mbids(artist_name: str) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    mbids: set[str] = set()

    with g.lib.transaction() as tx:
        rows = tx.query("SELECT id FROM items WHERE instr(artist, ?) > 0", (artist_name,))

    for row in rows:
        item = g.lib.get_item(row[0])
        if item is None:
            continue

        artist_names = _artist_names_from_item(item)
        artist_mbids = list(getattr(item, "mb_artistids", []) or [])
        if len(artist_names) != len(artist_mbids):
            continue

        for item_artist_name, mbid in zip(artist_names, artist_mbids, strict=False):
            if _normalize_artist_name(item_artist_name) == normalized_artist_name and mbid:
                mbids.add(str(mbid))

    return mbids


def _owned_release_group_ids(artist_name: str) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    release_group_ids: set[str] = set()

    with g.lib.transaction() as tx:
        rows = tx.query(
            "SELECT id FROM albums WHERE instr(albumartist, ?) > 0",
            (artist_name,),
        )

    for row in rows:
        album = g.lib.get_album(row[0])
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

    Strips common edition/remaster/bonus parenthetical suffixes so that
    "Névrose" and "Névrose (Deluxe Edition)" are treated as the same release.
    """
    t = title.casefold().strip()
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


def _owned_album_titles_normalized(artist_name: str) -> set[str]:
    normalized_artist_name = _normalize_artist_name(artist_name)
    titles: set[str] = set()

    with g.lib.transaction() as tx:
        rows = tx.query(
            "SELECT id FROM albums WHERE instr(albumartist, ?) > 0",
            (artist_name,),
        )

    for row in rows:
        album = g.lib.get_album(row[0])
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
                mbid = artist.get("id")
                if mbid:
                    return {mbid}
        # No exact match — take highest-scored result if score >= 90
        for artist in result.get("artist-list", []):
            score = int(artist.get("ext:score", 0) or 0)
            if score >= 90:
                mbid = artist.get("id")
                if mbid:
                    return {mbid}
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


def _missing_albums_from_musicbrainz(artist_name: str) -> list[dict[str, str | int | None]]:
    artist_mbids = _find_artist_mbids(artist_name)
    if not artist_mbids:
        # Artist not in beets library — search MB by name
        artist_mbids = _search_artist_mbid_from_mb(artist_name)
    if not artist_mbids:
        return []

    owned_release_group_ids = _owned_release_group_ids(artist_name)
    missing_by_release_group: dict[str, dict[str, str | int | None]] = {}

    for artist_mbid in artist_mbids:
        response = musicbrainzngs.browse_release_groups(artist=artist_mbid)
        for release_group in response.get("release-group-list", []):
            release_group_id = release_group.get("id")
            if not release_group_id or release_group_id in owned_release_group_ids:
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
    mb_titles_dedup: set[str],
) -> list[dict[str, str | int | None]]:
    """Query the Deezer public API for albums not already covered by MusicBrainz or owned.

    Uses `_normalize_for_dedup` for cross-source title matching so that edition
    variants (e.g. "Album (Deluxe)") are not listed twice.  Deezer-only results
    carry "deezer:<id>" as the release-group identifier.
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
            return []

        albums_url = f"https://api.deezer.com/artist/{artist_id}/albums?limit=200"
        with urllib.request.urlopen(albums_url, timeout=8) as req:  # noqa: S310
            albums_data = json.loads(req.read())

        results: list[dict[str, str | int | None]] = []
        for album in albums_data.get("data", []):
            title = album.get("title", "")
            dedup_key = _normalize_for_dedup(title)
            if dedup_key in owned_titles_dedup or dedup_key in mb_titles_dedup:
                continue

            year_str = str(album.get("release_date", "") or "")
            year: int | None = int(year_str[:4]) if len(year_str) >= 4 else None
            deezer_id = album.get("id")
            
            # Fetch individual album to get nb_tracks (not available in artist albums list)
            track_count: int | None = None
            if deezer_id:
                try:
                    album_url = f"https://api.deezer.com/album/{deezer_id}"
                    with urllib.request.urlopen(album_url, timeout=5) as req:  # noqa: S310
                        album_detail = json.loads(req.read())
                    track_count = album_detail.get("nb_tracks")
                except Exception:
                    pass

            results.append({
                "album": title,
                "year": year,
                "mb_releasegroupid": f"deezer:{deezer_id}" if deezer_id else None,
                "release_type": str(album.get("record_type", "album")),
                "cover_url": album.get("cover_medium") or album.get("cover") or None,
                "track_count": track_count,
            })
        return results

    except Exception:
        return []


def _missing_albums_from_sources(artist_name: str) -> list[dict[str, str | int | None]]:
    """Return missing albums for an artist merged from MusicBrainz and Deezer, sorted by year descending."""
    mb_missing = _missing_albums_from_musicbrainz(artist_name)
    mb_titles_dedup = {_normalize_for_dedup(str(m["album"])) for m in mb_missing}
    owned_titles = _owned_album_titles_normalized(artist_name)

    deezer_missing = _missing_albums_from_deezer(artist_name, owned_titles, mb_titles_dedup)

    all_missing = mb_missing + deezer_missing
    return sorted(
        all_missing,
        key=lambda a: (
            a["year"] is None,
            -(a["year"] or 0),
            str(a["album"]).casefold(),
        ),
    )


def get_artists_pandas(table: str, artist: str | None = None, include_size: bool = False) -> pd.DataFrame:
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

    with g.lib.transaction() as tx:
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


@artists_bp.route("/artists/<path:artist_name>", methods=["GET"])
@artists_bp.route("/artists", methods=["GET"], defaults={"artist_name": None})
async def all_artists(artist_name: str | None = None):
    """Get all artists from the database.

    This endpoint retrieves all artists from the database, splits them by
    specified separators and aggregates the data to count the number of items.
    """
    cache_key = _artists_cache_key(artist_name)
    cached = get_json_cache(cache_key)
    if cached is not None:
        return Response(cached, mimetype="application/json")

    artists_albums = (
        get_artists_pandas("albums", artist_name)
        .rename(
            columns={
                "count": "album_count",
                "last_added": "last_album_added",
                "first_added": "first_album_added",
            }
        )
        .set_index("artist")
    )
    artists_items = (
        get_artists_pandas("items", artist_name, include_size=True)
        .rename(
            columns={
                "count": "item_count",
                "last_added": "last_item_added",
                "first_added": "first_item_added",
            }
        )
        .set_index("artist")
    )
    # Join the two DataFrames on artist name and count the number of items and albums
    artists = artists_albums.join(
        artists_items,
        how="outer",
    ).reset_index()

    # Fill n_albums and n_items with 0 if they are NaN
    artists["album_count"] = artists["album_count"].fillna(0).astype(int)
    artists["item_count"] = artists["item_count"].fillna(0).astype(int)
    artists["total_size"] = artists["total_size"].fillna(0).astype(int)

    if artist_name is not None:
        if artists.empty:
            # Return a stub for followed-only artists (not yet in beets library)
            from beets_flask.discovery.followed_artists import is_followed

            if is_followed(artist_name):
                import json as _json

                stub = {
                    "artist": artist_name,
                    "album_count": 0,
                    "item_count": 0,
                    "total_size": 0,
                    "followed": True,
                }
                return Response(_json.dumps(stub), mimetype="application/json")
            raise NotFoundException(f"Artist '{artist_name}' not found.")
        else:
            payload = artists.iloc[0].to_json()
            set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
            return Response(payload, mimetype="application/json")

    payload = artists.to_json(orient="records")
    set_json_cache(cache_key, payload, ARTISTS_CACHE_TTL_SECONDS)
    return Response(payload, mimetype="application/json")


@artists_bp.route("/artists/<path:artist_name>/missing", methods=["GET"])
async def missing_albums_by_artist(artist_name: str):
    """Get missing albums for artist via Beets artist metadata + MusicBrainz.

    Uses exact artist MBIDs from Beets item metadata so featured artists without
    owned albums can still resolve their own missing release groups.
    """
    cache_key = _missing_cache_key(artist_name)
    cached = get_json_cache(cache_key)
    if cached is not None:
        return Response(cached, mimetype="application/json")

    try:
        missing = _missing_albums_from_sources(artist_name)
    except musicbrainzngs.musicbrainz.MusicBrainzError:
        payload = "[]"
        set_json_cache(cache_key, payload, MISSING_CACHE_TTL_SECONDS)
        return Response(payload, mimetype="application/json")

    payload = pd.DataFrame(missing).to_json(orient="records")
    set_json_cache(cache_key, payload, MISSING_CACHE_TTL_SECONDS)
    return Response(payload, mimetype="application/json")


@artists_bp.route("/missing-album-tracks", methods=["GET"])
async def missing_album_tracks():
    """Get the tracklist for a missing album by Deezer album ID or MB release group ID.

    Query param: id — either "deezer:<album_id>" or a bare MusicBrainz release-group UUID.
    """
    release_id = request.args.get("id", "").strip()
    if not release_id:
        return jsonify({"error": "id is required"}), 400

    if release_id.startswith("deezer:"):
        deezer_id = release_id[7:]
        try:
            tracks_url = f"https://api.deezer.com/album/{deezer_id}/tracks"
            with urllib.request.urlopen(tracks_url, timeout=8) as req:  # noqa: S310
                data = json.loads(req.read())
            tracks = [
                {
                    "title": t.get("title", ""),
                    "duration": t.get("duration"),
                    "track_position": t.get("track_position"),
                }
                for t in data.get("data", [])
            ]
            return jsonify(tracks)
        except Exception:
            return jsonify([])
    else:
        # MusicBrainz release group UUID
        try:
            return jsonify(_best_release_tracks_for_group(release_id))
        except Exception:
            return jsonify([])


@artists_bp.route("/artists/cache/refresh", methods=["POST"])
async def refresh_artists_cache():
    cleared = invalidate_artists_cache()
    return jsonify({"ok": True, "cleared": cleared})
