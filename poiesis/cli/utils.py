"""Info retrieval for CLI commands."""

from pathlib import Path
from typing import Any

import tomli

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.constants import get_poiesis_constants

api_constants = get_poiesis_api_constants()
constants = get_poiesis_constants()


def get_version() -> str:
    """Get version from pyproject.toml.

    Falls back to a default version if the file cannot be read.

    Returns:
        Version string from pyproject.toml or default
    """
    try:
        possible_paths = [
            Path("pyproject.toml"),
            Path(__file__).parent.parent.parent / "pyproject.toml",
        ]

        for path in possible_paths:
            if path.exists():
                with open(path, "rb") as f:
                    pyproject = tomli.load(f)
                    v: str = (
                        pyproject.get("tool", {})
                        .get("poetry", {})
                        .get("version", "0.1.0")
                    )
                    return v

        return "0.1.0"
    except Exception:
        return "0.1.0"


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


def get_basic_info() -> dict[str, Any]:
    """Get basic information about the project.

    Returns:
        Dictionary with basic information about the project.
    """
    info: dict[str, str] = {
        "version": get_version(),
    }

    if pyproject_data := get_pyproject_data():
        poetry_data = pyproject_data.get("tool", {}).get("poetry", {})

        if "authors" in poetry_data:
            info["authors"] = ", ".join(poetry_data["authors"])

        if "maintainers" in poetry_data:
            info["maintainers"] = ", ".join(poetry_data["maintainers"])

        if "repository" in poetry_data:
            info["repository"] = poetry_data["repository"]

        if "license" in poetry_data:
            info["license"] = poetry_data["license"]

    info |= {
        "TES version": api_constants.TES_VERSION,
        "TES spec hash": api_constants.SPEC_GIT_HASH,
        "environment": constants.ENVIRONMENT,
    }

    return dict(
        sorted({k.replace("_", " ").title(): v for k, v in info.items()}.items())
    )
