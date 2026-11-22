"""Poiesis-owned containers: trec, tif, tof and ack, with their env and security."""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING

from kubernetes.client import (
    V1Capabilities,
    V1Container,
    V1EnvVar,
    V1EnvVarSource,
    V1ObjectFieldSelector,
    V1SeccompProfile,
    V1SecretKeySelector,
    V1SecurityContext,
)

from poiesis.core import executor_shell
from poiesis.core.constants import (
    DRS_ALLOWED_HOSTS_ENV,
    DRS_BEARER_TOKEN_ENV,
    DRS_ENABLED_ENV,
    DRS_OBJECT_STORES_ENV,
    EXECUTOR_STREAMS_ENV,
    FILE_URL_ROOTS_ENV,
    FILER_PVC_PATH,
    FTP_ENABLED_ENV,
    OBJECT_STORE_DEFAULTS_ENV,
    OBJECT_STORES_ENV,
    OUTPUT_GLOB_FALLBACK_ENV,
)
from poiesis.core.executor_logs import Streams, encode_streams
from poiesis.core.filer.object_stores import (
    OPTIONAL_SECRET_KEYS,
    PROVIDER_SCHEMES,
    dump_stores,
    secret_env_name,
)
from poiesis.core.logging_config import LOG_FORMAT_ENV
from poiesis.core.pod_status import ACK_NAME, TIF_NAME, TOF_NAME, TREC_NAME
from poiesis.core.taskpod.config import PodSecurityEnforce
from poiesis.core.taskpod.paths import is_within, normalised
from poiesis.core.taskpod.volumes import (
    api_token_mount,
    identity_token_mounts,
    poiesis_mounts,
)

if TYPE_CHECKING:
    from kubernetes.client import V1VolumeMount

    from poiesis.core.taskpod.config import RuntimeConfig
    from poiesis.tes.models import TesTask


def build_trec(
    task: TesTask, config: RuntimeConfig, path_mounts: list[V1VolumeMount]
) -> V1Container:
    """Recorder native sidecar.

    Init container with `restartPolicy: Always` — the K8s 1.29+ native-sidecar
    form. The container stays alive for the lifetime of the Pod and observes
    init-phase container transitions.

    The only container that gets the ServiceAccount token: it watches the
    Pod and reads executor logs through the API. When executors write
    stdout or stderr to files, ``EXECUTOR_STREAMS_ENV`` says where on the
    task volume trec reads them (`executor_streams`).
    """
    env = downward_api_env() + poiesis_env(config)
    streams = executor_streams(task, path_mounts)
    if streams:
        env.append(V1EnvVar(name=EXECUTOR_STREAMS_ENV, value=encode_streams(streams)))
    container = V1Container(
        name=TREC_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=["poiesis", "trec", "run", "--task-id", require_id(task)],
        env=env,
        volume_mounts=[*poiesis_mounts(config), api_token_mount()],
        resources=config.recorder_resources,
        security_context=poiesis_security_context(config),
    )
    object.__setattr__(container, "restart_policy", "Always")
    return container


def downward_api_env() -> list[V1EnvVar]:
    """Env vars TRec needs from the downward API to identify its own Pod."""
    return [
        V1EnvVar(
            name="POIESIS_POD_NAME",
            value_from=V1EnvVarSource(
                field_ref=V1ObjectFieldSelector(field_path="metadata.name"),
            ),
        ),
        V1EnvVar(
            name="POIESIS_POD_NAMESPACE",
            value_from=V1EnvVarSource(
                field_ref=V1ObjectFieldSelector(field_path="metadata.namespace"),
            ),
        ),
    ]


def executor_streams(
    task: TesTask, path_mounts: list[V1VolumeMount]
) -> dict[int, Streams]:
    """Which executors write stdout/stderr to files, and where trec reads them.

    trec mounts the PVC at ``FILER_PVC_PATH``; a file under an executor
    path mount at ``<path>`` is at ``FILER_PVC_PATH/<path>`` there. Files
    elsewhere stay in the executor's container, out of trec's reach.
    """
    mount_paths = [mount.mount_path for mount in path_mounts]
    streams: dict[int, Streams] = {}
    for idx, executor in enumerate(task.executors):
        paths = {
            s: p
            for s, p in executor_shell.streams(executor).items()
            if s in ("stdout", "stderr")
        }
        if not paths:
            continue
        files = {}
        for stream, path in paths.items():
            normalised_path = normalised(path)
            if any(is_within(normalised_path, m) for m in mount_paths):
                files[stream] = posixpath.join(FILER_PVC_PATH, normalised_path[1:])
        streams[idx] = Streams(frozenset(paths), files)
    return streams


def build_tif(
    task: TesTask, config: RuntimeConfig, task_dirs: list[str]
) -> V1Container:
    """Input filer container; also creates `task_dirs` (see `volumes.task_dirs`)."""
    task_id = require_id(task)
    command = ["poiesis", "tif", "run", "--task-id", task_id]
    for path in task_dirs:
        command += ["--mkdir", path]
    return V1Container(
        name=TIF_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=command,
        env=[*filer_env(config), *drs_env(config)],
        volume_mounts=[*poiesis_mounts(config), *identity_token_mounts(config)],
        resources=config.filer_resources,
        security_context=poiesis_security_context(config),
    )


def build_tof(task: TesTask, config: RuntimeConfig) -> V1Container:
    """Output filer container."""
    task_id = require_id(task)
    return V1Container(
        name=TOF_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=["poiesis", "tof", "run", "--task-id", task_id],
        env=filer_env(config),
        volume_mounts=[*poiesis_mounts(config), *identity_token_mounts(config)],
        resources=config.filer_resources,
        security_context=poiesis_security_context(config),
    )


def filer_env(config: RuntimeConfig) -> list[V1EnvVar]:
    """Env vars TIF/TOF need.

    The mount path is *not* an operator knob — filer code reads
    ``poiesis.core.constants.FILER_PVC_PATH`` directly. The chart-internal
    DB DSN + S3 creds, plus operator extras, come through ``poiesis_env``.
    The output-glob fallback flag and the `file://` roots are set only when on.
    Object-store options and workload-identity settings (`config.filer_env`)
    and the named stores (`object_store_env`) go to TIF/TOF only.
    """
    env = [*poiesis_env(config), *config.filer_env, *object_store_env(config)]
    if config.output_glob_fallback:
        env.append(V1EnvVar(name=OUTPUT_GLOB_FALLBACK_ENV, value="true"))
    if config.file_url_roots:
        env.append(
            V1EnvVar(name=FILE_URL_ROOTS_ENV, value=",".join(config.file_url_roots))
        )
    if not config.ftp_enabled:
        env.append(V1EnvVar(name=FTP_ENABLED_ENV, value="false"))
    return env


def object_store_env(config: RuntimeConfig) -> list[V1EnvVar]:
    """Env vars for the named object stores, for TIF/TOF; none without any.

    The store table as one JSON value (no secret in it), the schemes whose
    default store is on, then each store's keys as references to its
    Secret (`object_stores.secret_env_name`).
    """
    if not config.object_stores:
        return []
    defaults = [s for s in PROVIDER_SCHEMES.values() if config.default_store_enabled(s)]
    env = [
        V1EnvVar(name=OBJECT_STORES_ENV, value=dump_stores(config.object_stores)),
        V1EnvVar(name=OBJECT_STORE_DEFAULTS_ENV, value=",".join(defaults)),
    ]
    for store in config.object_stores:
        env.extend(
            V1EnvVar(
                name=secret_env_name(store.name, key),
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=store.existing_secret,
                        key=key,
                        optional=True if key in OPTIONAL_SECRET_KEYS else None,
                    )
                ),
            )
            for key in store.secret_keys()
        )
    return env


def drs_env(config: RuntimeConfig) -> list[V1EnvVar]:
    """Env vars TIF, and only TIF, needs to resolve `drs://` inputs.

    The switch, the allowed hosts, the object stores a DRS URL may resolve
    to, and a reference to the bearer token for DRS servers. Nothing when
    DRS is off. Executors never get the token.
    """
    if not config.drs_enabled:
        return []
    stores = [s for s in ("s3", "gs", "az") if config.storage_enabled(s)]
    env = [
        V1EnvVar(name=DRS_ENABLED_ENV, value="true"),
        V1EnvVar(name=DRS_ALLOWED_HOSTS_ENV, value=",".join(config.drs_allowed_hosts)),
        V1EnvVar(name=DRS_OBJECT_STORES_ENV, value=",".join(stores)),
    ]
    if config.drs_secret:
        env.append(
            V1EnvVar(
                name=DRS_BEARER_TOKEN_ENV,
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=config.drs_secret, key=DRS_BEARER_TOKEN_ENV
                    )
                ),
            )
        )
    return env


def poiesis_env(config: RuntimeConfig) -> list[V1EnvVar]:
    """Env list shared by every poiesis-owned container.

    Chart-internal env (DATABASE_URL, AWS creds, etc.) first; operator
    extras second. Settings rejects collisions between the two sets at
    api startup so the order here is informational, not load-bearing.
    """
    env = [*config.extra_env, *config.taskpod_extra_env]
    if config.log_format is not None:
        env.append(V1EnvVar(name=LOG_FORMAT_ENV, value=config.log_format))
    return env


def build_ack_container(task: TesTask, config: RuntimeConfig) -> V1Container:
    """Terminal main container — reuses the poiesis image to avoid a second pull.

    K8s requires `containers:` to be non-empty. Init containers (TIF, the
    executors, TOF) carry the real work; once they finish, `ack` runs,
    exits 0, and the Pod reaches `Succeeded`. That terminal event is what
    TRec/TCtl watch for to close the task out.
    """
    task_id = require_id(task)
    return V1Container(
        name=ACK_NAME,
        image=config.poiesis_image,
        image_pull_policy=config.image_pull_policy,
        command=["poiesis", "ack", "run", "--task-id", task_id],
        resources=config.ack_resources,
        security_context=poiesis_security_context(config),
    )


def poiesis_security_context(config: RuntimeConfig) -> V1SecurityContext | None:
    """SecurityContext applied to poiesis-owned containers (trec/tif/tof/ack).

    Executor containers run user-supplied images and are deliberately exempt.

    - `RESTRICTED`: full PSS-restricted (runAsNonRoot, drop ALL, no privesc,
    seccomp RuntimeDefault, readOnlyRootFilesystem). The poiesis image is
    built to satisfy this profile.
    - `BASELINE`: the universally-safe subset (drop ALL, no privesc).
    - `OFF`: emit nothing.
    """
    if config.pod_security_enforce is PodSecurityEnforce.OFF:
        return None
    if config.pod_security_enforce is PodSecurityEnforce.BASELINE:
        return V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=V1Capabilities(drop=["ALL"]),
        )
    return V1SecurityContext(
        run_as_non_root=True,
        allow_privilege_escalation=False,
        read_only_root_filesystem=True,
        capabilities=V1Capabilities(drop=["ALL"]),
        seccomp_profile=V1SeccompProfile(type="RuntimeDefault"),
    )


def require_id(task: TesTask) -> str:
    """Return task.id, asserting it is set."""
    if task.id is None:
        msg = "TesTask.id must be set before manifest construction"
        raise ValueError(msg)
    return task.id
