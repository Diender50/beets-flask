# FastAPI Migration Context

## State: scaffolding done, migrations pending

Quart (async Flask) → FastAPI. Both ASGI on Uvicorn. Quart stays on :5001, FastAPI on :5002.
Migrate bottom-up: add each module to `server_v2/routes/`, register in `server_v2/routes/__init__.py`.

---

## Directory mapping

```
server/                           server_v2/
├── app.py                        ├── app.py              ✅ done
├── exceptions.py                 ├── exceptions.py       ✅ done (reuses server/exceptions.py)
├── utility.py                    ├── (reuse directly — no Quart imports)
├── routes/
│   ├── __init__.py               ├── routes/__init__.py  ✅ done
│   ├── monitor.py                ├── routes/monitor.py   ✅ done
│   ├── config.py                 ├── routes/config.py    ✅ done
│   ├── art_preview.py            ├── routes/art_preview.py ✅ done
│   ├── exception.py              ├── (handled in server_v2/exceptions.py — skip)
│   ├── frontend.py               ├── routes/frontend.py  ⬜ last (StaticFiles)
│   ├── inbox.py                  ├── routes/inbox.py     ⬜ complex
│   ├── db_models/                ├── routes/db_models/   ⬜ complex (state CRUD)
│   ├── discovery/__init__.py     ├── routes/discovery.py ⬜ complex
│   └── library/
│       ├── __init__.py           ├── routes/library/
│       ├── stats.py              │   ├── stats.py        ✅ done
│       ├── artists.py            │   ├── artists.py      ✅ done
│       ├── resources.py          │   ├── resources.py    ⬜ complex (decorators)
│       ├── artwork.py            │   ├── artwork.py      ✅ done
│       ├── audio.py              │   ├── audio.py        ⬜ (streaming + ffmpeg)
│       └── metadata.py           │   └── metadata.py     ✅ done
└── websocket/                    └── (skip for now — stays on Quart :5001)
    ├── __init__.py
    ├── status.py
    └── terminal.py
```

---

## Pattern translation

### Route definition
```python
# Quart
bp = Blueprint("x", __name__, url_prefix="/x")
@bp.route("/foo", methods=["GET"])
async def get_foo(): ...

# FastAPI
router = APIRouter(prefix="/x", tags=["x"])
@router.get("/foo")
async def get_foo(): ...
```

### Request context `g.lib`
```python
# Quart — set in library/__init__.py @before_request
g.lib.get_album(id)

# FastAPI — inject via Depends
from beets_flask.server_v2.dependencies import BeetsLib
async def get_album(id: int, lib: BeetsLib): ...
    return lib.get_album(id)
```

### Query parameters
```python
# Quart
from quart import request
query = request.args.get("q", "")
expand = request.args.get("expand") is not None

# FastAPI
async def endpoint(q: str = "", expand: bool = False): ...
```

### Request body (JSON)
```python
# Quart
data = await request.get_json()

# FastAPI — use Pydantic model or dict
from pydantic import BaseModel
class Payload(BaseModel):
    field: str
async def endpoint(body: Payload): ...
# or for freeform dicts:
from typing import Any
async def endpoint(body: dict[str, Any]): ...
```

### JSON response
```python
# Quart
return jsonify({"key": "value"})
return jsonify(result), 201

# FastAPI — return dict directly (CustomJSONResponse handles encoding)
return {"key": "value"}
# with status code:
from fastapi import Response
from fastapi.responses import JSONResponse
return JSONResponse(content={...}, status_code=201)
# or use response_model + status_code in decorator:
@router.post("/foo", status_code=201)
async def foo() -> dict: ...
```

### Binary/streaming response
```python
# Quart
return await send_file(path, mimetype="image/jpeg")

# FastAPI
from fastapi.responses import FileResponse, StreamingResponse
return FileResponse(path, media_type="image/jpeg")
# or for in-memory bytes:
return Response(content=bytes_data, media_type="image/jpeg")
```

### Error handling
```python
# Quart — raise ApiException subclass anywhere, blueprint error_bp catches it
raise NotFoundException("not found")

# FastAPI — same, registered in server_v2/exceptions.py
raise NotFoundException("not found")  # unchanged
```

### Before-request hook (library __init__.py attach_library)
```python
# Quart — @library_bp.before_request
@library_bp.before_request
async def attach_library(): g.lib = _open_library(config)

# FastAPI — replaced by BeetsLib Depends() in each route
# No before_request equivalent needed; each route gets lib injected.
# If multiple routes need the same state, use a router-level dependency:
router = APIRouter(dependencies=[Depends(some_check)])
```

### Path converters
```python
# Quart — <path:query> matches slash-containing strings
@bp.route("/items/<path:query>", methods=["GET"])

# FastAPI
@router.get("/items/{query:path}")
async def items(query: str = ""): ...
```

### DELETE with query param
```python
# Quart — @resource decorator reads request.method
@bp.route("/album/<int:id>", methods=["GET", "DELETE", "PATCH"])
@resource(Album)
async def album(id: int): ...

# FastAPI — split into separate endpoints
@router.get("/album/{id}")
async def get_album(id: int, lib: BeetsLib): ...

@router.delete("/album/{id}")
async def delete_album(id: int, delete: bool = False, lib: BeetsLib): ...

@router.patch("/album/{id}")
async def patch_album(id: int, body: dict, lib: BeetsLib): ...
```

---

## Key invariants to preserve

### Custom JSON encoder
`server_v2/json_encoder.py` `CustomJSONResponse` handles:
- `bytes` → `str` (UTF-8 decode) — used for beets paths
- `datetime/date` → ISO format
- `dataclass` → `asdict()`
- `Enum` → `.value`

All routes use `default_response_class=CustomJSONResponse` set on the FastAPI app.
**Do not** use `jsonify()` in v2 — just return dicts.

### DB session lifecycle
`server_v2/dependencies.py` `get_db()` replaces `@app.teardown_appcontext`.
For routes using SQLAlchemy directly: inject `DbSession`.
For routes using beets lib transaction (`g.lib.transaction()`): inject `BeetsLib`.

### `PaginatedQuery` / `Cursor` classes (resources.py)
These are pure Python (no Quart imports). Copy them verbatim to `server_v2/routes/library/resources.py`.
The `PaginatedQuery.total()` method calls `g.lib.transaction()` — change to take `lib` param:
```python
def total(self, lib: Library) -> int:
    with lib.transaction() as tx:  # was: g.lib.transaction()
        ...
```

### `pop_query_param` utility
`server/utility.py` — no Quart imports, reuse directly:
```python
from beets_flask.server.utility import pop_query_param
```

### socketio (WebSocket)
**Do not migrate yet.** `server/websocket/` stays on Quart :5001.
When ready: `socketio.ASGIApp(sio, fastapi_app)` wraps the FastAPI ASGI app.
`sio` uses `AsyncRedisManager` — both apps can share the same Redis channel.

### `@exception_as_return_value` decorator (for RQ workers)
Lives in `server/exceptions.py` — keep using it in worker code, not in routes.

---

## Module complexity notes

### `config.py` — EASY
No DB, no beets lib. Two GET endpoints. Return config dicts.

### `art_preview.py` — EASY
Single GET `/art?url=...`. Proxies image from Spotify. Use `httpx` (async) instead of `requests`:
```python
import httpx
async with httpx.AsyncClient() as client:
    r = await client.get(url)
return Response(content=r.content, media_type=r.headers["content-type"])
```
Add `httpx` to pyproject.toml deps.

### `stats.py` — EASY
Single GET `/library/stats`. Needs `BeetsLib`. Returns dict aggregates.

### `monitor.py` — ✅ DONE
Pattern: pure RQ/Redis, no DB, no lib.

### `metadata.py` — EASY
Single GET `/items/{id}/metadata`. Needs `BeetsLib`. Uses `tinytag`.

### `library/artists.py` — MEDIUM
Multiple GETs. Needs `BeetsLib`. Uses Redis cache (`library_cache.py`).
`g.lib` references throughout → replace with `lib: BeetsLib`.

### `library/artwork.py` — MEDIUM
GET `/items/{id}/artwork`, `/albums/{id}/artwork`. Returns `Response(bytes, media_type=...)`.
PIL image manipulation — keep as-is.

### `library/audio.py` — MEDIUM
GET `/items/{id}/audio`. Streaming response with ffmpeg transcoding.
```python
from fastapi.responses import StreamingResponse
return StreamingResponse(generator(), media_type="audio/mpeg")
```

### `library/resources.py` — COMPLEX
- Split `@resource` / `@resource_query` decorators into separate GET/DELETE/PATCH endpoints.
- `PaginatedQuery.total()` needs `lib` param injected.
- `g.lib` → `lib: BeetsLib` everywhere.
- `Cursor`, `PaginatedQuery`, `_rep`, `_repr_Item`, `_rep_Album` — copy verbatim.

### `inbox.py` — COMPLEX
Import pipeline: multipart form, RQ job enqueueing, DB session, folder state.
Needs both `DbSession` and `BeetsLib`. Many endpoints.

### `routes/db_models/` — COMPLEX
State CRUD for SQLAlchemy models (session, folder, candidate).
Currently registered dynamically via `register_state_models()` at startup.
In FastAPI: create one router per model, register in `routes/__init__.py`.

### `discovery/__init__.py` — COMPLEX
Download job CRUD, Deemix/Slskd/Squidwtf search/queue, artist follow.
Many endpoints, external provider calls.

### `frontend.py` — LAST
```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")
# Must be mounted AFTER all API routes (catch-all).
```

---

## Migration order (bottom-up)

1. `config` — no deps
2. `art_preview` — no deps (add httpx)
3. `library/stats` — BeetsLib
4. `library/metadata` — BeetsLib
5. `library/artists` — BeetsLib + Redis
6. `library/artwork` — BeetsLib
7. `library/audio` — BeetsLib + ffmpeg streaming
8. `library/resources` — BeetsLib, refactor decorators, fix PaginatedQuery.total()
9. `inbox` — DbSession + BeetsLib + RQ
10. `db_models/` — DbSession
11. `discovery` — DbSession + external providers
12. `websocket` — last, wrap FastAPI with socketio.ASGIApp
13. `frontend` — very last (catch-all static mount)

---

## How to run both servers

Inside container (scripts live in `/repo/backend/`):
```bash
python /repo/backend/launch_redis_workers.py &
python /repo/backend/launch_watchdog_worker.py &
uvicorn beets_flask.server.app:create_app --factory --port 5001 &  # Quart
python /repo/backend/launch_fastapi.py                             # FastAPI :5002
```

From host via docker exec:
```bash
docker exec beets-flask python /repo/backend/launch_fastapi.py
```

Test new endpoint:
```bash
curl http://localhost:5002/api_v1/monitor/queues
# FastAPI auto-docs:
open http://localhost:5002/docs
```

---

## Files that stay unchanged (no migration needed)

| File | Reason |
|---|---|
| `beets_flask/database/` | SQLAlchemy — framework-agnostic |
| `beets_flask/config/` | confuse + env — no Quart |
| `beets_flask/redis.py` | RQ/Redis — no Quart |
| `beets_flask/importer/` | Beets pipeline — no Quart |
| `beets_flask/invoker/` | RQ enqueue — no Quart |
| `beets_flask/watchdog/` | inotify — no Quart |
| `beets_flask/discovery/providers/` | external HTTP — no Quart |
| `beets_flask/library_cache.py` | Redis cache — no Quart |
| `beets_flask/disk.py` | dataclasses — no Quart |
| `beets_flask/logger.py` | stdlib logging — no Quart |
| `beets_flask/server/exceptions.py` | pure Python — reused in v2 |
| `beets_flask/server/utility.py` | pure Python — reused in v2 |
| `generate_types.py` | TypeScript gen — no Quart |
| `launch_redis_workers.py` | no Quart |
| `launch_watchdog_worker.py` | no Quart |
| `launch_db_init.py` | no Quart |

---

## Quart-specific imports to remove per file

Find all Quart-specific imports:
```bash
grep -r "from quart" beets_flask/server/routes/
grep -r "import quart" beets_flask/server/routes/
```

Replace list:
- `from quart import Blueprint` → `from fastapi import APIRouter`
- `from quart import g` → inject via `Depends`
- `from quart import request` → FastAPI query/body params or `from fastapi import Request`
- `from quart import jsonify` → return `dict` directly
- `from quart import Response` → `from fastapi import Response`
- `from quart import abort` → `raise HTTPException(status_code=...)`
- `from quart import send_file` → `from fastapi.responses import FileResponse`
- `from werkzeug.exceptions import HTTPException` → `from fastapi import HTTPException`

---

## Pyproject.toml: new deps added

```toml
"fastapi>=0.115.0",
"pydantic>=2.0",
# add when migrating art_preview:
# "httpx>=0.27.0",
```
