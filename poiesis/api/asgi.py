"""Configure Gunicorn to run the ASGI server.

Uses Uvicorn as the worker for the Poiesis API.
"""

import importlib
import multiprocessing

from gunicorn.app.base import BaseApplication

from poiesis.api.constants import get_poiesis_api_constants
from poiesis.constants import get_poiesis_constants

constants = get_poiesis_constants()
api_constants = get_poiesis_api_constants()

BIND = f"{api_constants.Gunicorn.HOST}:{api_constants.Gunicorn.PORT}"
WORKERS = (
    api_constants.Gunicorn.WORKERS
    if api_constants.Gunicorn.WORKERS
    else (multiprocessing.cpu_count() * 2) + 1
)
TIMEOUT = api_constants.Gunicorn.TIMEOUT
WORKER_CLASS = "uvicorn.workers.UvicornWorker"


def import_app_from_string(import_string):
    """Import an application object from a string.

    Args:
        import_string (str): The import string in the format "<module>:<attribute>".

    Returns:
        Any: The imported attribute object.

    Raises:
        ImportError: If the import string is invalid or the attribute is not found.
    """
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
    """Run the Gunicorn server with the Poiesis app."""

    class PoiesisApplication(BaseApplication):
        def __init__(self, app_import_path, options=None):
            self.options = options or {}
            self.app_import_path = app_import_path
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return import_app_from_string(self.app_import_path)

    options = {
        "bind": BIND,
        "workers": int(WORKERS),
        "timeout": int(TIMEOUT),
        "worker_class": WORKER_CLASS,
    }

    app_import_path = "poiesis.api.app:app"

    PoiesisApplication(app_import_path, options).run()
