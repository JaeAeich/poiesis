"""TES paths: normalising them, and the rules a path must follow to be mounted.

The rules raise ``ValueError``; the API translates this into HTTP 400.
"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING

from poiesis.api.tes.models import TesFileType
from poiesis.core.constants import FILER_PVC_PATH

if TYPE_CHECKING:
    from poiesis.api.tes.models import TesTask


_GLOB_CHARS = frozenset("*?[]{}")


def dir_candidates(task: TesTask) -> set[str]:
    """Directories `volumes.executor_path_mounts` mounts, inputs aside, as given."""
    candidates: set[str] = set(task.volumes or [])
    for out in task.outputs or []:
        if _GLOB_CHARS.intersection(out.path):
            candidates.add(glob_free_dir(out.path))
        elif out.type == TesFileType.DIRECTORY:
            candidates.add(out.path)
        else:
            candidates.add(posixpath.dirname(out.path))
    return candidates


def declared_paths(task: TesTask) -> list[tuple[str, str]]:
    """Every path the task declares, with what declares it, for messages."""
    paths = [(f"volumes[{i}]", v) for i, v in enumerate(task.volumes or [])]
    paths += [
        (f"inputs[{i}].path", inp.path) for i, inp in enumerate(task.inputs or [])
    ]
    for i, out in enumerate(task.outputs or []):
        paths.append((f"outputs[{i}].path", out.path))
        if out.path_prefix:
            paths.append((f"outputs[{i}].path_prefix", out.path_prefix))
    return paths


def reject_parent_components(task: TesTask) -> None:
    """Reject ``..`` in TES paths.

    The executor mounts use normalised paths, but TIF and TOF join the path
    as given onto ``FILER_PVC_PATH``; with ``..`` the two could disagree.
    ``.`` and repeated slashes are harmless and normalised.
    """
    for name, path in declared_paths(task):
        if ".." in path.split("/"):
            msg = f"{name} {path!r} has a `..` component; give the path without it"
            raise ValueError(msg)


def reject_paths_below_file_inputs(task: TesTask) -> None:
    """Reject paths below a FILE input.

    TIF stages a FILE input as a file, so nothing can be created below it.
    (A FILE output at the input's own path is fine: it is mounted at its
    parent directory, which covers the input.)
    """
    file_inputs = [
        (f"inputs[{i}].path", normalised(inp.path))
        for i, inp in enumerate(task.inputs or [])
        if inp.type != TesFileType.DIRECTORY
    ]
    for name, path in declared_paths(task):
        normalised_path = normalised(path)
        for input_field, file_path in file_inputs:
            if normalised_path != file_path and is_within(normalised_path, file_path):
                msg = f"{name} {path!r} is below {input_field} {file_path!r}, a file"
                raise ValueError(msg)


def normalised(path: str) -> str:
    """``posixpath.normpath``, without POSIX's leading ``//``."""
    return "/" + posixpath.normpath(path).lstrip("/")


def mount_path(path: str) -> str:
    """Normalise a TES path for mounting; reject paths that can't be mounted."""
    if not posixpath.isabs(path):
        msg = f"TES paths must be absolute: {path!r}"
        raise ValueError(msg)
    normalised_path = normalised(path)
    if normalised_path == "/":
        msg = (
            f"TES path {path!r} would need the task volume mounted at `/`; "
            "put inputs, outputs and volumes in a directory, e.g. `/data`"
        )
        raise ValueError(msg)
    if is_within(normalised_path, FILER_PVC_PATH):
        msg = (
            f"TES path {path!r} is in {FILER_PVC_PATH}, where Poiesis stages "
            "task files; use another directory"
        )
        raise ValueError(msg)
    return normalised_path


def glob_free_dir(path: str) -> str:
    """Return the directory before the first wildcard of `path`."""
    first = min(path.index(char) for char in _GLOB_CHARS if char in path)
    return posixpath.dirname(path[:first])


def is_within(path: str, outer: str) -> bool:
    """True if `path` is `outer` or below it, comparing whole components."""
    return path == outer or path.startswith(outer.rstrip("/") + "/")


def depth(path: str) -> tuple[int, str]:
    """Sort key: shallower paths first, then by name."""
    return (path.count("/"), path)
