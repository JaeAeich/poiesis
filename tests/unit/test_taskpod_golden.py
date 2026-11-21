"""Golden manifests for the TaskPod builder.

Each case builds the PVC and Job for a fixed task and runtime config and
compares their JSON, as the kubernetes client sends it, byte for byte with
`golden/taskpod/<case>.json`. The cases cover every branch of the builder,
so a change to `poiesis.core.taskpod` that alters a manifest fails here.
Tasks the builder rejects are compared, by error message, with
`golden/taskpod/rejected.json`.

The files are never written by a normal run, and never in CI. After a
deliberate manifest change, regenerate them and review the diff:

    POIESIS_WRITE_GOLDEN=1 uv run pytest tests/unit/test_taskpod_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from kubernetes.client import (
    ApiClient,
    V1EnvVar,
    V1EnvVarSource,
    V1ResourceRequirements,
    V1SecretKeySelector,
)

from poiesis.api.tes.models import (
    TesExecutor,
    TesFileType,
    TesInput,
    TesOutput,
    TesResources,
    TesTask,
)
from poiesis.core.constants import FILE_URL_ROOTS_ENV
from poiesis.core.taskpod import (
    PodSecurityEnforce,
    RuntimeConfig,
    attach_pvc_owner,
    build_taskpod_job,
)

GOLDEN = Path(__file__).parent / "golden" / "taskpod"
WRITE_ENV = "POIESIS_WRITE_GOLDEN"

#: Roots the API process allows for `file://` URLs while the cases run.
FILE_ROOTS = "/srv/shared"

BASE = RuntimeConfig(taskpod_namespace="poiesis", poiesis_image="poiesis:golden")

EXEC = TesExecutor(image="busybox:1.36", command=["echo", "hi"])

# Everything an operator can set, at once.
FULL_CONFIG = RuntimeConfig(
    taskpod_namespace="tasks",
    poiesis_image="registry.example.org/poiesis:1.2.3",
    pvc_storage_class="fast-ssd",
    pvc_access_modes=("ReadWriteMany",),
    pvc_default_size_gi=5,
    pvc_max_size_gi=50,
    pvc_labels={"cost-center": "lab-a", "poiesis.io/task": "overridden"},
    pvc_annotations={"backup.velero.io/backup-volumes": "task-data"},
    image_pull_policy="Always",
    taskpod_service_account="poiesis-taskpod",
    job_ttl_seconds=600,
    active_deadline_seconds=7200,
    grace_period_seconds=45,
    image_pull_secrets=("regcred", "mirror"),
    postgres_ca_configmap="pg-ca",
    filer_resources=V1ResourceRequirements(
        requests={"cpu": "100m", "memory": "128Mi"}, limits={"memory": "256Mi"}
    ),
    recorder_resources=V1ResourceRequirements(requests={"cpu": "50m"}),
    ack_resources=V1ResourceRequirements(limits={"cpu": "10m"}),
    extra_env=[
        V1EnvVar(
            name="DATABASE_URL",
            value_from=V1EnvVarSource(
                secret_key_ref=V1SecretKeySelector(name="poiesis-db", key="url")
            ),
        ),
        V1EnvVar(name="AWS_REGION", value="eu-central-1"),
    ],
    taskpod_extra_env=[V1EnvVar(name="HTTPS_PROXY", value="http://proxy:3128")],
    taskpod_extra_volumes=[
        {"name": "ref", "persistentVolumeClaim": {"claimName": "r"}}
    ],
    taskpod_extra_volume_mounts=[
        {"name": "ref", "mountPath": "/ref", "readOnly": True}
    ],
    output_glob_fallback=True,
    file_url_roots=("/srv/shared", "/scratch"),
)


def _task(**fields: Any) -> TesTask:
    fields.setdefault("id", "golden")
    fields.setdefault("executors", [EXEC])
    return TesTask(**fields)


def _inp(path: str, **fields: Any) -> TesInput:
    fields.setdefault("url", "s3://bucket/in")
    return TesInput(path=path, **fields)


def _out(path: str, **fields: Any) -> TesOutput:
    fields.setdefault("url", "s3://bucket/out")
    return TesOutput(path=path, **fields)


#: case name → (task, config); each one exercises a branch of the builder.
CASES: dict[str, tuple[TesTask, RuntimeConfig]] = {
    "minimal": (_task(), BASE),
    "inputs-only": (
        _task(
            inputs=[
                _inp("/data/in.txt"),
                TesInput(path="/data/inline.txt", content="hello"),
                _inp("/data/http.txt", url="https://example.org/f"),
                _inp("/data/local.txt", url="file:///srv/shared/f"),
            ]
        ),
        BASE,
    ),
    "outputs-only": (_task(outputs=[_out("/results/out.txt")]), BASE),
    "multiple-executors": (
        _task(
            executors=[
                EXEC,
                TesExecutor(image="alpine:3.20", command=["sh", "-c", "ls /"]),
                TesExecutor(image="python:3.13", command=["python", "-V"]),
            ]
        ),
        BASE,
    ),
    "ignore-error": (
        _task(
            executors=[
                TesExecutor(image="busybox", command=["false"], ignore_error=True),
                EXEC,
            ]
        ),
        BASE,
    ),
    "streams": (
        _task(
            inputs=[_inp("/data/in.txt")],
            outputs=[_out("/data/out/log.txt")],
            executors=[
                TesExecutor(
                    image="busybox",
                    command=["cat"],
                    stdin="/data/in.txt",
                    stdout="/data/out/stdout.txt",
                    stderr="/var/log/stderr.txt",
                ),
                TesExecutor(image="busybox", command=["date"], stdout="/data/out/d"),
                TesExecutor(image="busybox", command=["true"], stderr="/var/err"),
            ],
        ),
        BASE,
    ),
    "nested-volumes": (
        _task(
            volumes=["/mnt/task", "/mnt/task/usage", "/scratch//tmp/./x"],
            inputs=[_inp("/mnt/task/in.txt")],
            outputs=[_out("/mnt/task/usage/u.json")],
        ),
        BASE,
    ),
    "directories": (
        _task(
            inputs=[
                _inp("/data/ref", type=TesFileType.DIRECTORY, url="s3://bucket/ref/"),
                _inp("/data/ref2/file.txt"),
            ],
            outputs=[
                _out("/results/all", type=TesFileType.DIRECTORY),
                _out("/logs/*.log", path_prefix="/logs"),
                _out("/other/a[0-9]/b", type=TesFileType.DIRECTORY),
                _out("/deep/out/file.txt"),
            ],
        ),
        BASE,
    ),
    "workdir-env": (
        _task(
            executors=[
                TesExecutor(
                    image="busybox",
                    command=["pwd"],
                    workdir="/data",
                    env={"B": "2", "A": "1"},
                )
            ]
        ),
        BASE,
    ),
    "disk-set": (_task(resources=TesResources(disk_gb=2.3)), BASE),
    "disk-zero": (_task(resources=TesResources(disk_gb=0)), BASE),
    "disk-under-max": (
        _task(resources=TesResources(disk_gb=10)),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            pvc_max_size_gi=10,
            pvc_default_size_gi=3,
        ),
    ),
    "disk-default": (
        _task(resources=TesResources(cpu_cores=2)),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            pvc_default_size_gi=7,
        ),
    ),
    "disk-default-floor": (
        _task(),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            pvc_default_size_gi=0,
            pvc_storage_class="",
        ),
    ),
    "backend-params-non-strict": (
        _task(resources=TesResources(backend_parameters={"VmSize": "x"})),
        BASE,
    ),
    "backend-params-strict-empty": (
        _task(
            resources=TesResources(
                backend_parameters={}, backend_parameters_strict=True
            )
        ),
        BASE,
    ),
    "full-config": (
        _task(
            inputs=[_inp("/data/in.txt")],
            outputs=[_out("/data/out/*.txt", path_prefix="/data/out")],
            volumes=["/work"],
            executors=[
                TesExecutor(
                    image="busybox",
                    command=["sh", "-c", "ls"],
                    workdir="/work",
                    env={"X": "y"},
                    stdout="/work/out.log",
                    ignore_error=True,
                )
            ],
            resources=TesResources(disk_gb=20),
        ),
        FULL_CONFIG,
    ),
    "pod-security-baseline": (
        _task(inputs=[_inp("/data/in.txt")], outputs=[_out("/data/out.txt")]),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            pod_security_enforce=PodSecurityEnforce.BASELINE,
        ),
    ),
    "pod-security-off": (
        _task(inputs=[_inp("/data/in.txt")], outputs=[_out("/data/out.txt")]),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            pod_security_enforce=PodSecurityEnforce.OFF,
        ),
    ),
    "no-deadline-no-ttl": (
        _task(),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            active_deadline_seconds=None,
            job_ttl_seconds=None,
        ),
    ),
    "literal-env": (
        _task(outputs=[_out("/data/out.txt")]),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            extra_env=[
                V1EnvVar(name="DATABASE_URL", value="postgresql://db/poiesis"),
                V1EnvVar(name="AWS_ACCESS_KEY_ID", value="key"),
            ],
        ),
    ),
    "secret-env": (
        _task(outputs=[_out("/data/out.txt")]),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            extra_env=[
                V1EnvVar(
                    name="DATABASE_URL",
                    value_from=V1EnvVarSource(
                        secret_key_ref=V1SecretKeySelector(name="db", key="url")
                    ),
                ),
                V1EnvVar(
                    name="AWS_ACCESS_KEY_ID",
                    value_from=V1EnvVarSource(
                        secret_key_ref=V1SecretKeySelector(name="s3", key="id")
                    ),
                ),
            ],
        ),
    ),
    "operator-extras-only": (
        _task(),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            taskpod_extra_env=[V1EnvVar(name="TZ", value="UTC")],
            taskpod_extra_volumes=[{"name": "cfg", "configMap": {"name": "cfg"}}],
            taskpod_extra_volume_mounts=[{"name": "cfg", "mountPath": "/etc/cfg"}],
        ),
    ),
    # an operator mount without `mountPath` is passed through unchecked
    "operator-mount-no-path": (
        _task(volumes=["/ref/sub"]),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            taskpod_extra_volume_mounts=[{"name": "ref"}],
        ),
    ),
}

#: case name → (task, config) the builder must refuse; the golden file holds
#: the exact message of each.
REJECTED: dict[str, tuple[TesTask, RuntimeConfig]] = {
    "missing-id": (TesTask(executors=[EXEC]), BASE),
    "input-scheme": (_task(inputs=[_inp("/data/x", url="ftp://host/x")]), BASE),
    "input-file-outside-roots": (
        _task(inputs=[_inp("/data/x", url="file:///etc/passwd")]),
        BASE,
    ),
    "output-scheme": (
        _task(outputs=[_out("/data/x", url="ftp://host/x")]),
        BASE,
    ),
    "parent-component": (_task(volumes=["/data/../etc"]), BASE),
    "parent-component-prefix": (
        _task(outputs=[_out("/data/*.txt", path_prefix="/data/../x")]),
        BASE,
    ),
    "below-file-input": (
        _task(inputs=[_inp("/data/in.txt")], outputs=[_out("/data/in.txt/x")]),
        BASE,
    ),
    "relative-path": (_task(volumes=["data"]), BASE),
    "root-mount": (_task(volumes=["/"]), BASE),
    "staging-dir": (_task(volumes=["/transfer/x"]), BASE),
    "operator-mount-conflict": (
        _task(volumes=["/ref/sub"]),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            taskpod_extra_volume_mounts=[{"name": "ref", "mountPath": "/ref/"}],
        ),
    ),
    "relative-stream": (
        _task(executors=[TesExecutor(image="busybox", command=["x"], stdout="o")]),
        BASE,
    ),
    "disk-over-max": (
        _task(resources=TesResources(disk_gb=10.2)),
        RuntimeConfig(
            taskpod_namespace="poiesis",
            poiesis_image="poiesis:golden",
            pvc_max_size_gi=10,
        ),
    ),
    "backend-params-strict": (
        _task(
            resources=TesResources(
                backend_parameters={"VmSize": "x", "Accel": "y"},
                backend_parameters_strict=True,
            )
        ),
        BASE,
    ),
}


@pytest.fixture(autouse=True)
def _file_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fix the `file://` roots the input/output checks read from the env."""
    monkeypatch.setenv(FILE_URL_ROOTS_ENV, FILE_ROOTS)


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def _check(name: str, text: str) -> None:
    """Compare `text` with the golden file `name`, or write it on request."""
    path = GOLDEN / name
    if os.environ.get(WRITE_ENV):
        if os.environ.get("CI"):
            pytest.fail(f"{WRITE_ENV} is set in CI; golden files are never rewritten")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return
    assert path.exists(), f"{path} is missing; see this module's docstring"
    assert path.read_text() == text, f"{name} differs from the golden manifest"


@pytest.mark.parametrize("case", sorted(CASES))
def test_manifest_matches_golden(case: str) -> None:
    """The PVC and Job built for `case` are the golden ones, byte for byte."""
    task, config = CASES[case]
    pvc, job = build_taskpod_job(task, config)
    serialise = ApiClient().sanitize_for_serialization
    _check(f"{case}.json", _dump({"job": serialise(job), "pvc": serialise(pvc)}))


def test_pvc_owner_matches_golden() -> None:
    """`attach_pvc_owner` adds the golden ownerReference."""
    pvc, _ = build_taskpod_job(*CASES["minimal"])
    attach_pvc_owner(pvc, "0000-uid", "task-golden")
    serialise = ApiClient().sanitize_for_serialization
    _check("pvc-owner.json", _dump(serialise(pvc)))


def test_rejections_match_golden() -> None:
    """Every task the builder refuses, with the exact message."""
    messages: dict[str, str] = {}
    for case, (task, config) in REJECTED.items():
        with pytest.raises(ValueError) as caught:  # noqa: PT011 - message is checked
            build_taskpod_job(task, config)
        messages[case] = str(caught.value)
    _check("rejected.json", _dump(messages))
