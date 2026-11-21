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

#: Env var listing the directories `file://` URLs may point into, comma
#: separated. Sourced from ``taskpods.fileUrlRoots``; the API reads it to
#: accept or refuse a task, TIF/TOF read it again before touching a path.
#: Unset or empty turns the `file://` scheme off.
FILE_URL_ROOTS_ENV: str = "POIESIS_FILE_URL_ROOTS"

#: Env vars the API sets on TIF/TOF for S3 options the AWS SDKs have no
#: standard variable for (``s3.*`` chart values). Unset keeps the default.
S3_VIRTUAL_HOSTED_STYLE_ENV: str = "POIESIS_S3_VIRTUAL_HOSTED_STYLE"
S3_SERVER_SIDE_ENCRYPTION_ENV: str = "POIESIS_S3_SERVER_SIDE_ENCRYPTION"
S3_SSE_KMS_KEY_ID_ENV: str = "POIESIS_S3_SSE_KMS_KEY_ID"
S3_REQUESTER_PAYS_ENV: str = "POIESIS_S3_REQUESTER_PAYS"

#: Directory under which TIF/TOF, and no other container, find the
#: ServiceAccount token they trade for cloud credentials: one subdirectory
#: per provider, holding ``token``.
IDENTITY_TOKEN_DIR: str = "/var/run/secrets/poiesis/identity"  # noqa: S105 - a path
