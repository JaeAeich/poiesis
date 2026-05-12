"""Runtime-shared constants for core services.

The TaskPod spec builder and the filer strategies must agree on the path
at which the shared Task PVC is mounted inside every container. The spec
builder injects `POIESIS_FILER_PVC_PATH` into TIF/TOF; strategies read it
here. Default `/transfer` matches `RuntimeConfig.filer_pvc_mount_path`.
"""

from __future__ import annotations

import os

FILER_PVC_PATH: str = os.environ.get("POIESIS_FILER_PVC_PATH", "/transfer")
