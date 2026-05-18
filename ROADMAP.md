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

---

## Phase 5: Global Artist Discovery (Aurral-style)

### 5.1 Product Goal
- Add new global tab: `/library/discovery`
- Show artist discovery generated from current library profile
- Allow following artists directly from discovery cards
- Keep strict "not in library yet" filtering

### 5.2 Discovery Algorithm Target (match Aurral approach)

#### Aurral code reading scope (required before implementation)
- Read and map pipeline from these files:
  - `backend/services/discoveryService.js`
  - `backend/services/discoveryRecommendations.js`
  - `backend/routes/discovery.js`
  - `frontend/src/pages/DiscoverPage.jsx`
  - `.tests/discovery/recommendation-pipeline.test.js`

#### Aurral patterns to port
- Seed building from library (+ optional listen history), weighted by source and affinity
- Candidate expansion via Last.fm `artist.getSimilar` + tag context (`artist.getTopTags`)
- Identity merge/dedup by MBID + normalized name keys
- Composite scoring with interpretable components:
  - `scoreSimilarity`
  - `scoreTagAffinity`
  - `scoreSeedCoverage`
  - `scoreNovelty`
  - `scorePopularityPenalty`
- Discovery modes (`safer`, `balanced`, `deeper`) using score multipliers
- Rerank pass with diversity penalty + user feedback boosts/penalties
- Reason codes (example: tag affinity, multi-seed consensus, deeper pick)
- Blocklist filtering (artist/tag)
- Exclude artists already in library
- Cached discovery payload + stale-refresh behavior

### 5.3 Backend Plan (beets-flask)

#### 5.3.1 New module layout
- Add `backend/beets_flask/discovery/artist_recommendations.py`
- Add `backend/beets_flask/discovery/scoring.py`
- Add `backend/beets_flask/discovery/cache.py`
- Add `backend/beets_flask/discovery/feedback.py`

#### 5.3.2 New API routes
- `GET /api/discovery/artists`
  - Return recommendations, based_on seeds, top tags, last_updated, stale flag
- `POST /api/discovery/artists/refresh`
  - Trigger recompute in background
- `POST /api/discovery/feedback`
  - Actions: `more_like_this`, `less_like_this`, `already_known`, `hide_for_now`
- `GET /api/discovery/blocklist`
- `PUT /api/discovery/blocklist`

#### 5.3.3 Discovery data contract (v1)
- Recommended artist fields:
  - `id` (MBID if available)
  - `name`
  - `image`
  - `score_total`
  - `confidence`
  - `matched_tags[]`
  - `supporting_seeds[]`
  - `source_types[]`
  - `reason_codes[]`
  - `discovery_tier`

#### 5.3.4 External provider behavior
- Last.fm required for similar-artist expansion
- ListenBrainz optional for history seeds
- MusicBrainz used to resolve/normalize MBIDs when missing
- Add request limiter + retry budget + provider health metrics

### 5.4 Frontend Plan

#### 5.4.1 New route and shell
- Add route: `frontend/src/routes/library/discovery.route.tsx`
- Add top-level nav tab entry for Discovery

#### 5.4.2 Discovery page sections (MVP)
- Hero: "Based on your library" seeds
- Recommended artists rail/grid
- Global trending rail (optional in MVP if data available)
- Tag exploration chips from top tags

#### 5.4.3 Artist card actions
- Follow artist (integrate with existing followed artist flow)
- Add to blocklist
- Feedback actions:
  - more like this
  - less like this
  - already known
  - hide for now

#### 5.4.4 UX constraints
- Never show artist already in library
- Always show short reason text (seed/tag/source based)
- Poll/WebSocket refresh while backend is recomputing

### 5.5 Follow Artist Integration
- Reuse existing follow endpoints and storage
- If not existing, add:
  - `POST /api/discovery/artists/:id/follow`
  - `DELETE /api/discovery/artists/:id/follow`
- Add optimistic UI state + retry toast on failure

### 5.6 Testing Plan

#### Backend tests
- Unit tests for seed weighting, candidate merge, score computation, rerank
- Contract tests for discovery endpoints
- Failure-path tests when Last.fm unavailable

#### Frontend tests
- Route rendering with empty, loading, and populated states
- Card action tests (follow, feedback, blocklist)
- Dedup and "already in library" exclusion tests

### 5.7 Rollout Plan
- Feature flag: `discovery.artist.enabled`
- Internal-only rollout first
- Capture metrics:
  - recommendation count
  - follow-through rate
  - feedback distribution
  - refresh latency

### 5.8 Definition of Done (Phase 5)
- Discovery tab visible and functional
- Recommendations generated from library profile with Aurral-style scoring flow
- Follow action works from discovery cards
- Feedback and blocklist alter subsequent ranking/filtering
- Tests passing for scoring + API + UI actions

---

## External Project Reading Backlog (for stronger discovery engine)

### Priority A (read now)
- **Aurral** (`lklynet/aurral`)
  - Why: direct reference implementation for this feature
  - Extract: seed model, scoring, feedback rerank, cache/staleness mechanics

- **ListenBrainz Server** (`metabrainz/listenbrainz-server`)
  - Why: mature similarity + recommendation datasets/pipelines
  - Extract: similarity index generation, popularity windows, recommendation batch jobs

- **Koel** (`koel/koel`)
  - Why: practical "similar songs" + smart playlist rule engine in production UI
  - Extract: playlist rule DSL, similarity fallback behavior, actionable UX patterns

### Priority B (read next)
- **Lidarr** (`Lidarr/Lidarr`)
  - Why: artist/album metadata lifecycle and follow/monitor model
  - Extract: metadata refresh boundaries, candidate matching heuristics, follow defaults

- **beets + plugins** (`beetbox/beets`)
  - Why: configurable metadata/tag signal extraction already aligned with this stack
  - Extract: tag normalization, whitelist/ignorelist strategy, fallback semantics

- **Music Assistant** (`music-assistant/server`)
  - Why: multi-provider architecture patterns for robust media services
  - Extract: provider abstraction patterns, capability flags, resilient orchestration

- **Navidrome** (`navidrome/navidrome`)
  - Why: battle-tested streaming server integration patterns
  - Extract: playback context API patterns, user-scope state handling

### Research outputs required from each project
- One-page note per project:
  - architecture sketch
  - ranking/filtering ideas worth porting
  - risk items to avoid
  - integration opportunities for beets-flask

