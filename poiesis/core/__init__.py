"""poiesis code package.

This package contains the TaskPod side of Poiesis: the TaskPod spec builder,
TRec, TCtl, and the filer services (TIF/TOF).

This file is also used to initialize the logging configuration.
"""

from poiesis.core.logging_config import setup_logging

setup_logging()
