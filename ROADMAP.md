# Beets-Flask Fork: Library Visualization & Discovery Roadmap

**Goal:** Enhanced music library browser + album discovery/acquisition for Beets-Flask.

## Phase 1: Library Visualization (MVP)

### 1.1 Artist List View
- **Frontend:** New route `/library/artists`
- **Display:** Table/grid of all artists in Beets library
- Columns: Artist name, album count, track count, total size
- Sort/filter by name, count, date added
- Styling: Match existing Beets-Flask UI theme

### 1.2 Artist Details View
- **Route:** `/library/artists/<artist_id>`
- **Sections:**
  - Artist info (name, image, track/album count)
  - Albums table (title, year, track count, status)
  - Missing albums section (via Beets Missing plugin)
    - Shows albums not in collection
    - Status indicator (missing vs. in library)
- **Backend API:** New endpoints in `server/routes/`
  - `GET /api/library/artists` — all artists
  - `GET /api/library/artists/<id>` — artist detail + albums
  - `GET /api/library/artists/<id>/missing` — missing albums

### 1.3 Backend Integration
- **Database models:** Extend/query Beets' library models (artist, album, item)
- **Beets Missing plugin:** Query missing albums API
- **Caching:** Redis cache artist summaries (expire on library rescan)
- **Endpoints:** RESTful routes, WebSocket support for real-time updates

### 1.4 Frontend Components
- Artist list component (table with pagination)
- Artist detail page (layout + album tables)
- Missing album indicator/badge
- Album status filter

---

## Phase 2: Album Discovery

### 2.1 Search Integration
- **Frontend:** Search bar in artist/album views
- **Search providers:**
  - Beets web API / MusicBrainz
  - Spotify (metadata lookup)
  - Optional: Last.fm
- **Display:** Search results with artist/album info, release dates, artwork

### 2.2 Album Acquisition UI
- **Download button/action** on missing albums
- **Provider selection:** Modal/dropdown to choose source (slskd, Deemix, etc.)
- **Status tracking:** Queue display, download progress
- **Integration:** Connect to existing Beets import pipeline

---

## Phase 3: Download Providers

### 3.1 Slskd Integration
- **API:** Query slskd for album availability
- **Download:** Enqueue files via slskd
- **Status:** Monitor transfer progress
- **Endpoints:** `POST /api/download/slskd/search`, `POST /api/download/slskd/queue`

### 3.2 Deemix Integration
- **Auth:** Deezer credentials management
- **Search:** Query Deemix for releases
- **Download:** Queue albums for download
- **Quality:** Allow user-selectable bitrate/quality

### 3.3 Future Providers
- Bandcamp API
- SoundCloud
- Other P2P / streaming platforms

---

## Phase 4: Workflow Polish & Automation

### 4.1 Import Integration
- Auto-import downloaded albums into Beets
- Trigger library rescan after import
- Update missing album status in real-time

### 4.2 Notifications
- WebSocket updates on download completion
- Email/in-app alerts for failed downloads
- Progress notifications during import

### 4.3 Batch Operations
- Download all missing albums from artist
- Bulk operations on selected albums
- Download history/logs

---

## Architecture Notes

**No existing Beets-Flask changes:**
- New routes in `server/routes/library.py` (or `discovery.py`)
- New models only if needed; leverage Beets' existing ORM
- Isolate new features behind feature flag (optional)

**Frontend structure:**
- `src/routes/library/` — artist/album pages
- `src/components/Library*` — reusable components
- `src/api/library.ts` — API client for new endpoints

**Backend structure:**
- `beets_flask/server/routes/` — new route files
- `beets_flask/database/` — extend models if needed
- `beets_flask/discovery/` — new module for provider integrations
  - `providers/slskd.py`
  - `providers/deemix.py`
  - `providers/musicbrainz.py`

---

## Dependencies to Evaluate

- **Beets plugins:** beets-missing, beets-web
- **APIs:** MusicBrainz, Spotify, Deemix SDK, slskd REST API
- **Python:** requests, musicbrainzngs (or similar)
- **Frontend:** Chart/table libraries (if needed)

---

## Success Criteria

- ✅ Phase 1: Browse artists → see albums & missing albums
- ✅ Phase 2: Search for albums, see results
- ✅ Phase 3: Download via ≥2 providers (slskd + Deemix)
- ✅ Phase 4: Seamless workflow from discovery to library

