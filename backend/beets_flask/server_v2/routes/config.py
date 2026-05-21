from fastapi import APIRouter
from fastapi.responses import JSONResponse

from beets_flask.config import get_config

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/all")
async def get_all() -> dict:
    config = get_config()
    return _serializable(config.flatten(redact=True))


@router.get("/")
async def get_basic() -> dict:
    config = get_config()
    from beets import __version__ as beets_version
    from beets.metadata_plugins import find_metadata_source_plugins

    data_sources: list[str] = [p.__class__.data_source for p in find_metadata_source_plugins()]

    return {
        "gui": _serializable(config["gui"].flatten(redact=True)),
        "import": {k: config["import"][k].get() for k in ["duplicate_action"]},
        "match": {
            k: config["match"][k].get()
            for k in ["strong_rec_thresh", "medium_rec_thresh"]
        }
        | {
            k: config["match"][k].as_str_seq()
            for k in ["album_disambig_fields", "singleton_disambig_fields"]
        },
        "plugins": config["plugins"].as_str_seq(),
        "data_sources": data_sources,
        "beets_version": beets_version,
    }


@router.get("/yaml/beets")
async def get_raw_beets() -> dict:
    config = get_config()
    path = config.get_beets_config_path()
    with open(path) as f:
        content = f.read()
    return {"path": path, "content": content}


@router.get("/yaml")
async def get_raw() -> dict:
    config = get_config()
    path = config.get_beets_flask_config_path()
    with open(path) as f:
        content = f.read()
    return {"path": path, "content": content}


@router.post("/refresh")
async def refresh() -> dict:
    from beets_flask.config.beets_config import refresh_config

    refresh_config()
    return {"status": "ok"}


def _serializable(input):
    if isinstance(input, bytes):
        return input.decode("utf-8")
    elif isinstance(input, dict):
        return {k: _serializable(v) for k, v in input.items()}
    elif isinstance(input, list):
        return [_serializable(element) for element in input]
    return input
