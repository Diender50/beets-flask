# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Beets-Flask is a full-stack web interface around [Beets](https://beets.io/), a music organizer/tagger. It generates import previews, lets users confirm/tweak matches via a web GUI, then commits imports to the library. The app runs as a Docker container (Alpine Linux) with a Python/Quart backend and a React/TypeScript frontend.

## Commands

### Frontend (`frontend/`)

```bash
pnpm dev            # Vite dev server (port 5173, proxies /api_v1/* and /socket.io to :5001)
pnpm build          # Production build
pnpm lint           # ESLint (zero warnings allowed)
pnpm format         # Prettier (write)
pnpm format-check   # Prettier (check only)
pnpm check-types    # tsc --noEmit
```

### Backend (`backend/`)

```bash
# Testing
pytest                        # Run all tests
pytest tests/path/test_foo.py # Run single test file
pytest -k "test_name"         # Run specific test

# Linting & formatting
ruff check beets_flask/       # Lint
ruff format beets_flask/      # Format
mypy beets_flask/             # Type check

# Dev launchers (run separately in dev)
python launch_db_init.py           # Init/migrate database
python launch_redis_workers.py     # Start RQ background workers
python launch_watchdog_worker.py   # Start inbox file-system monitor
python generate_types.py           # Regenerate TypeScript types from Python models
```

### Docker

```bash
docker compose -f docker/docker-compose.dev.yaml up    # Dev (mounts repo)
docker compose -f docker/docker-compose.yaml up        # Production
docker compose -f docker/docker-compose.tests.yaml up  # Test environment
```

## Architecture

### Backend (`backend/beets_flask/`)

| Module | Role |
|---|---|
| `server/app.py` | Quart app factory; registers routes and Socket.IO |
| `server/routes/` | REST API endpoints (inbox, library, config, discovery, art, audio, terminal) |
| `server/websocket/` | Socket.IO handlers for real-time status and terminal I/O |
| `importer/` | Beets import pipeline: state machine that drives preview generation and actual imports |
| `database/` | SQLAlchemy models (SQLite); session management |
| `invoker/` | RQ job enqueueing — all long-running work goes through Redis queues |
| `watchdog/` | Inotify-based folder monitor; triggers preview jobs when new inbox folders appear |
| `discovery/` | Pluggable download providers (Deemix, Slskd, Squidwtf, Last.fm) |
| `config/` | Confuse-based config loading; merges beets config + beets-flask overrides |

Key runtime dependencies: **Quart** (async ASGI), **Redis + RQ** (job queue), **SQLAlchemy** (SQLite ORM), **python-socketio** (WebSocket), **Uvicorn** (ASGI server).

### Frontend (`frontend/src/`)

| Directory | Role |
|---|---|
| `routes/` | Page components — file-based routing via TanStack Router (route tree auto-generated into `routeTree.gen.ts`) |
| `components/` | Reusable UI components built on MUI |
| `api/` | Typed API client functions (fetch wrappers + React Query hooks) |
| `main.tsx` | App entry point; sets up Router, QueryClient, Socket.IO |
| `theme.tsx` | MUI theme customization |

Key libraries: **TanStack Router** (file-based, code-split), **TanStack React Query** (server state), **Material-UI**, **Socket.IO client** (live updates), **XTerm** (web terminal), **WaveSurfer.js** (audio preview).

### Data flow

1. Watchdog detects a new inbox folder → enqueues an RQ import-preview job
2. RQ worker runs beets in preview mode → stores results in SQLite
3. Socket.IO pushes status updates to the browser
4. User reviews previews in the UI, selects candidates, and confirms
5. Backend executes the real beets import → library updated

### Dev proxy

In local dev the Vite server (`:5173`) proxies `^/api_v1/.*` and `/socket.io` to the Quart server at `127.0.0.1:5001`. In production, Quart serves the built frontend directly on port 5001.

### Type generation

Python models are the source of truth for shared types. Run `python generate_types.py` (in `backend/`) after changing data models to regenerate TypeScript types.

---

## Fork Roadmap

This repository is a fork extending the upstream Beets-Flask with library visualization and music discovery. Work is organized in 5 phases.

### Phase 1 — Library Visualization (MVP) ✅
- Artist list view at `/library/artists` (name, album count, track count, size, sort/filter)
- Artist detail view at `/library/artists/<id>` with albums table and missing albums (via Beets Missing plugin)
- New backend endpoints: `GET /api/library/artists`, `/artists/<id>`, `/artists/<id>/missing`
- New frontend components under `src/routes/library/` and `src/components/Library*`

### Phase 2 — Album Discovery
- Search bar integrated into artist/album views
- Providers: MusicBrainz, Spotify (metadata), Last.fm (optional)
- Search results with artwork, release dates, download action on missing albums

### Phase 3 — Download Providers
- **slskd** (Soulseek): search availability, queue transfers, monitor progress
  - Endpoints: `POST /api/download/slskd/search`, `POST /api/download/slskd/queue`
- **Deemix** (Deezer): auth, search, download with user-selectable bitrate/quality

### Phase 4 — Workflow Polish & Automation
- Auto-import downloaded albums into Beets + library rescan trigger
- WebSocket notifications on download completion / import failure
- Batch operations: download all missing albums for an artist, bulk selects, download history

### Phase 5 — Global Artist Discovery (Aurral-style)
New tab `/library/discovery` with library-profile-based artist recommendations.

**Algorithm (ported from [Aurral](https://github.com/lklynet/aurral)):**
- Seed building from library (+ optional ListenBrainz listen history), weighted by source/affinity
- Candidate expansion via Last.fm `artist.getSimilar` + tag context (`artist.getTopTags`)
- Identity merge/dedup by MBID + normalized name keys
- Composite score components: `scoreSimilarity`, `scoreTagAffinity`, `scoreSeedCoverage`, `scoreNovelty`, `scorePopularityPenalty`
- Discovery modes: `safer` / `balanced` / `deeper` (score multipliers)
- Rerank pass with diversity penalty + user feedback boosts/penalties
- Reason codes shown in UI (tag affinity, multi-seed consensus, deeper pick…)
- Blocklist filtering (artist/tag); always excludes artists already in library
- Cached discovery payload with stale-refresh behavior (feature flag: `discovery.artist.enabled`)

**New backend modules to add:**
- `beets_flask/discovery/artist_recommendations.py`
- `beets_flask/discovery/scoring.py`
- `beets_flask/discovery/cache.py`
- `beets_flask/discovery/feedback.py`

**New API routes:**
- `GET /api/discovery/artists` — recommendations with seeds, tags, staleness flag
- `POST /api/discovery/artists/refresh` — background recompute
- `POST /api/discovery/feedback` — actions: `more_like_this`, `less_like_this`, `already_known`, `hide_for_now`
- `GET|PUT /api/discovery/blocklist`

**External providers for Phase 5:** Last.fm (required), ListenBrainz (optional history seeds), MusicBrainz (MBID normalization). All need request limiter + retry budget.

**Reference projects to read before implementing Phase 5:**
- `lklynet/aurral` — direct reference for seed model, scoring, feedback rerank, cache/staleness
- `metabrainz/listenbrainz-server` — similarity index generation, recommendation batch jobs
- `Lidarr/Lidarr` — artist/album metadata lifecycle and follow/monitor model
