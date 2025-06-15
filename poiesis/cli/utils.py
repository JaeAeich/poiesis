"""Info retrieval for CLI commands."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import tomli

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.constants import get_poiesis_constants

api_constants = get_poiesis_api_constants()
constants = get_poiesis_constants()


@lru_cache
def get_version() -> str:
    """Get version from pyproject.toml."""
    if pyproject_data := get_pyproject_data():
        version: str = pyproject_data.get("project", {}).get("version", "UNKNOWN")
        return version
    else:
        return "UNKNOWN"


@lru_cache
def get_pyproject_data() -> dict[str, Any]:
    """Get all data from pyproject.toml.

    Returns:
        Dictionary with pyproject.toml data or None if not found
    """
    try:
        possible_paths = [
            Path("pyproject.toml"),
            Path(__file__).parent.parent.parent / "pyproject.toml",
        ]

        for path in possible_paths:
            if path.exists():
                with open(path, "rb") as f:
                    return tomli.load(f)

        return {}
    except Exception:
        return {}


@lru_cache
def get_basic_info() -> dict[str, Any]:
    """Get basic information about the project.

    Returns:
        Dictionary with basic information about the project.
    """
    info: dict[str, Any] = {
        "version": get_version(),
    }

    if pyproject_data := get_pyproject_data():
        project_data = pyproject_data.get("project", {})

        if "authors" in project_data:
            info["authors"] = ", ".join(
                author.get("name", "") for author in project_data["authors"]
            )

        if "maintainers" in project_data:
            info["maintainers"] = ", ".join(
                maintainer.get("name", "") for maintainer in project_data["maintainers"]
            )

        if "urls" in project_data and "Repository" in project_data["urls"]:
            info["repository"] = project_data["urls"]["Repository"]

        if "urls" in project_data and "Documentation" in project_data["urls"]:
            info["documentation"] = project_data["urls"]["Documentation"]

        if "license" in project_data:
            info["license"] = project_data["license"]

    info |= {
        "TES version": api_constants.TES_VERSION,
        "TES spec hash": api_constants.SPEC_GIT_HASH,
        "environment": constants.ENVIRONMENT,
    }

    # Format keys (e.g., "tes version") and sort for display
    return dict(
        sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
    )
