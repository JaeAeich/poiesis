"""Runtime-shared constants for core services.

The TaskPod spec builder and the filer strategies must agree on the path
at which the shared Task PVC is mounted inside every container. The path
is invisible to operators and TES clients alike; changing it accomplishes
nothing observable, so it's a plain constant rather than a config knob.
"""

FILER_PVC_PATH: str = "/transfer"
