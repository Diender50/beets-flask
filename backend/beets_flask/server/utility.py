"""Pure Python request parameter helpers — framework-agnostic copy of server/utility.py."""

from collections.abc import Callable
from pathlib import Path
from typing import cast

from typing_extensions import TypeVar

from beets_flask.invoker.job import ExtraJobMeta
from beets_flask.server.exceptions import InvalidUsageException

R = TypeVar("R")
D = TypeVar("D", default=None)


def pop_query_param(
    params: dict,
    key: str,
    convert_func: Callable[..., R],
    default: D | None = None,
    error_message: str | None = None,
) -> D | R:
    if params is None:
        return default

    value = params.pop(key, None)
    if value is None:
        return cast(D, default)

    try:
        value = convert_func(value)
    except (ValueError, TypeError):
        if error_message is None:
            error_message = f"Invalid parameter '{key}'"
        raise InvalidUsageException(error_message)

    return value


def pop_extra_meta(params: dict, n_jobs=1) -> list[ExtraJobMeta]:
    job_refs: list[str] | None = pop_query_param(
        params=params, key="job_frontend_refs", convert_func=list, default=None
    )
    if job_refs is None:
        return [{} for _ in range(n_jobs)]
    if not isinstance(job_refs, list):
        raise InvalidUsageException("job_frontend_refs must be a list")
    if len(job_refs) != n_jobs:
        raise InvalidUsageException(f"job_frontend_refs must be a list of length {n_jobs}")
    return [ExtraJobMeta(job_frontend_ref=job_ref) for job_ref in job_refs]


def pop_folder_params(
    params: dict,
    allow_mismatch: bool = False,
    allow_empty: bool = True,
) -> tuple[list[str], list[Path]]:
    folder_hashes: list[str] = pop_query_param(params, "folder_hashes", list, default=[])
    folder_paths: list[Path] = pop_query_param(
        params, "folder_paths", lambda x: [Path(p) for p in x], default=[]
    )
    if not allow_mismatch and len(folder_hashes) != len(folder_paths):
        raise InvalidUsageException("folder_hashes and folder_paths must be of the same length")
    if not allow_empty and (len(folder_hashes) + len(folder_paths)) == 0:
        raise InvalidUsageException("folder_hashes and folder_paths cannot be empty")
    return folder_hashes, folder_paths


def pop_paths_param(params: dict, key: str, default: D | None = None) -> list[Path] | D:
    def ensure_list_of_path(obj) -> list[Path]:
        if not isinstance(obj, list):
            return [Path(obj)]
        return [Path(o) for o in obj]

    return pop_query_param(
        params=params, key=key, convert_func=ensure_list_of_path,
        default=default, error_message=f"Invalid parameter '{key}'",
    )
