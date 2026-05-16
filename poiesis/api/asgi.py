"""Gunicorn entrypoint for the Poiesis API.

Runs `poiesis.api.app:app` under Gunicorn with a single Uvicorn worker.
Bind/port/timeout are intentionally hardcoded — every Poiesis process
in production runs behind a Kubernetes Service on the same port, and
scaling is done by adding Pod replicas, not by widening per-pod worker
count (asyncpg's pool isn't shared across processes).
"""

import importlib

from gunicorn.app.base import BaseApplication

_BIND = "0.0.0.0:8000"
_WORKERS = 1
_TIMEOUT = 120
_WORKER_CLASS = "uvicorn.workers.UvicornWorker"


def import_app_from_string(import_string):
    """Resolve `<module>:<attribute>` to the attribute object."""
    module_str, _, attrs_str = import_string.partition(":")
    if not module_str or not attrs_str:
        raise ImportError(
            f"Import string '{import_string}' must be in format '<module>:<attribute>'"
        )
    try:
        module = importlib.import_module(module_str)
    except ImportError as exc:
        if exc.name != module_str:
            raise exc from None
        raise ImportError(f"Could not import module '{module_str}'") from exc
    try:
        for attr in attrs_str.split("."):
            module = getattr(module, attr)
        return module
    except AttributeError as exc:
        raise ImportError(
            f"Attribute '{attrs_str}' not found in module '{module_str}'"
        ) from exc


def run():
    """Run Gunicorn with the Poiesis app."""

    class PoiesisApplication(BaseApplication):
        def __init__(self, app_import_path, options=None):
            self.options = options or {}
            self.app_import_path = app_import_path
            super().__init__()

        def load_config(self):  # type: ignore[override]
            for key, value in self.options.items():
                if self.cfg and key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):  # type: ignore[override]
            return import_app_from_string(self.app_import_path)

    options = {
        "bind": _BIND,
        "workers": _WORKERS,
        "timeout": _TIMEOUT,
        "worker_class": _WORKER_CLASS,
    }

    PoiesisApplication("poiesis.api.app:app", options).run()
