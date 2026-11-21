"""Runtime-shared constants for core services.

The TaskPod spec builder and the filer strategies must agree on the path
at which the shared Task PVC is mounted inside every container. The path
is invisible to operators and TES clients alike; changing it accomplishes
nothing observable, so it's a plain constant rather than a config knob.
"""

FILER_PVC_PATH: str = "/transfer"

#: Env var the API sets on TIF/TOF when the operator turns on
#: ``taskpods.outputGlobFallback``: an output glob that matches no file then
#: uploads everything under the output's ``path_prefix`` instead of nothing.
OUTPUT_GLOB_FALLBACK_ENV: str = "POIESIS_OUTPUT_GLOB_FALLBACK"

#: Env var the API sets on trec when an executor sets TES ``stdout`` or
#: ``stderr``: which streams go to files and where trec finds them on the
#: task volume (see ``poiesis.core.executor_logs.Streams``).
EXECUTOR_STREAMS_ENV: str = "POIESIS_EXECUTOR_STREAMS"
