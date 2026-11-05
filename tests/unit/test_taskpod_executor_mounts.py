"""Executors must see inputs and outputs at their TES paths (#108).

TIF stages ``inputs[].path`` to ``/transfer/<path>`` on the task PVC and TOF
collects ``outputs[].path`` from there. Executors used to get the PVC only at
``/transfer``, so ``/data/in.txt`` was missing and ``/data/out.txt`` was never
collected.
"""

from __future__ import annotations

import posixpath

import pytest

from poiesis.api.tes.models import (
    TesExecutor,
    TesFileType,
    TesInput,
    TesOutput,
    TesTask,
)
from poiesis.core.constants import FILER_PVC_PATH
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

CONFIG = RuntimeConfig(taskpod_namespace="tasks", poiesis_image="poiesis:test")


def make_task(
    inputs: list[TesInput] | None = None,
    outputs: list[TesOutput] | None = None,
    volumes: list[str] | None = None,
    executors: int = 1,
) -> TesTask:
    return TesTask(
        id="t1",
        inputs=inputs,
        outputs=outputs,
        volumes=volumes,
        executors=[
            TesExecutor(image="busybox:1.36", command=["true"])
            for _ in range(executors)
        ],
    )


def file_input(path: str) -> TesInput:
    return TesInput(path=path, content="x")


def dir_input(path: str) -> TesInput:
    return TesInput(path=path, url="s3://bucket/dir", type=TesFileType.DIRECTORY)


def file_output(path: str, path_prefix: str | None = None) -> TesOutput:
    return TesOutput(path=path, url="s3://bucket/out", path_prefix=path_prefix)


def dir_output(path: str) -> TesOutput:
    return TesOutput(path=path, url="s3://bucket/out", type=TesFileType.DIRECTORY)


def executor_containers(task: TesTask) -> list:
    _, job = build_taskpod_job(task, CONFIG)
    return [
        c for c in job.spec.template.spec.init_containers if c.name.startswith("exec-")
    ]


def path_mounts(task: TesTask) -> dict[str, str]:
    """Executor mounts at TES paths: mount path → PVC subPath."""
    (container,) = executor_containers(task)
    return {
        m.mount_path: m.sub_path
        for m in container.volume_mounts
        if m.mount_path != FILER_PVC_PATH
    }


def pvc_location(mounts: dict[str, str], path: str) -> str | None:
    """Where on the PVC the executor reads or writes `path`, if anywhere."""
    for mount_path, sub_path in mounts.items():
        if path == mount_path:
            return sub_path
        if path.startswith(mount_path + "/"):
            return posixpath.join(sub_path, path[len(mount_path) + 1 :])
    return None


def filer_location(path: str) -> str:
    """Where TIF stages, and TOF collects, `path` on the PVC."""
    return path.lstrip("/")


def test_executor_sees_inputs_and_outputs_where_the_filers_put_them():
    # the task from #108
    task = make_task(
        inputs=[file_input("/data/in.txt")],
        outputs=[file_output("/data/out.txt")],
    )

    mounts = path_mounts(task)

    assert mounts == {"/data": "data"}
    for path in ("/data/in.txt", "/data/out.txt"):
        assert pvc_location(mounts, path) == filer_location(path)


def test_every_declared_path_resolves_to_its_filer_location():
    inputs = [
        file_input("/ref/genome.fa"),
        file_input("/in.txt"),
        dir_input("/samples"),
        file_input("/work/params.json"),
    ]
    outputs = [
        file_output("/work/out/result.vcf"),
        dir_output("/reports/html"),
        file_output("/glob/*.bam", path_prefix="/glob/"),
    ]
    task = make_task(inputs=inputs, outputs=outputs, volumes=["/scratch"])

    mounts = path_mounts(task)

    paths = [i.path for i in inputs] + [
        "/work/out/result.vcf",
        "/reports/html/index.html",
        "/glob/a.bam",
        "/samples/s1.fq",
        "/scratch/tmp",
    ]
    for path in paths:
        assert pvc_location(mounts, path) == filer_location(path), path


def test_mounts_follow_v01_rules():
    task = make_task(
        inputs=[
            file_input("/in.txt"),  # file at the root: the file itself
            file_input("/ref/genome.fa"),  # file: the file itself
            dir_input("/samples"),  # directory: the directory
            file_input("/work/params.json"),  # covered by the output below
        ],
        outputs=[
            file_output("/work/out.txt"),  # file: its parent directory
            dir_output("/reports/html"),  # directory: the directory
            file_output("/glob/*.bam", path_prefix="/glob/"),  # path_prefix
            file_output("/runs/*/stats.txt"),  # before the first wildcard
        ],
        volumes=["/scratch"],
    )

    assert path_mounts(task) == {
        "/glob": "glob",
        "/in.txt": "in.txt",
        "/ref/genome.fa": "ref/genome.fa",
        "/reports/html": "reports/html",
        "/runs": "runs",
        "/samples": "samples",
        "/scratch": "scratch",
        "/work": "work",
    }


def test_nested_paths_keep_only_the_outer_mount():
    task = make_task(
        inputs=[dir_input("/data"), file_input("/data/sub/in.txt")],
        outputs=[file_output("/data/sub/deeper/out.txt")],
        volumes=["/data/tmp"],
    )

    assert path_mounts(task) == {"/data": "data"}


def test_sibling_prefixes_are_not_nested():
    # `/data2` is not inside `/data`
    task = make_task(outputs=[file_output("/data/a.txt"), file_output("/data2/b.txt")])

    assert path_mounts(task) == {"/data": "data", "/data2": "data2"}


def test_paths_are_normalised():
    task = make_task(
        inputs=[file_input("/data/./x/../in.txt")],
        outputs=[file_output("/data/out.txt")],
    )

    assert path_mounts(task) == {"/data": "data"}


def test_every_executor_gets_the_mounts_and_keeps_the_staging_mount():
    task = make_task(outputs=[file_output("/data/out.txt")], executors=2)

    for container in executor_containers(task):
        mounts = [(m.mount_path, m.sub_path) for m in container.volume_mounts]
        assert mounts == [(FILER_PVC_PATH, None), ("/data", "data")]


def test_operator_mounts_still_reach_executors():
    config = RuntimeConfig(
        taskpod_namespace="tasks",
        poiesis_image="poiesis:test",
        taskpod_extra_volume_mounts=[{"name": "ref", "mountPath": "/ref"}],
    )
    task = make_task(outputs=[file_output("/data/out.txt")])

    _, job = build_taskpod_job(task, config)
    (container,) = [
        c for c in job.spec.template.spec.init_containers if c.name == "exec-0"
    ]

    assert container.volume_mounts[-1] == {"name": "ref", "mountPath": "/ref"}


def test_task_without_paths_gets_no_extra_mounts():
    assert path_mounts(make_task()) == {}


def test_filer_containers_are_unchanged():
    task = make_task(
        inputs=[file_input("/data/in.txt")], outputs=[file_output("/data/out.txt")]
    )

    _, job = build_taskpod_job(task, CONFIG)
    filers = [
        c for c in job.spec.template.spec.init_containers if c.name in {"tif", "tof"}
    ]

    assert len(filers) == 2
    for container in filers:
        assert [m.mount_path for m in container.volume_mounts] == [FILER_PVC_PATH]


@pytest.mark.parametrize(
    ("task", "message"),
    [
        (make_task(volumes=["/"]), "mounted at `/`"),
        (make_task(inputs=[dir_input("/")]), "mounted at `/`"),
        (make_task(inputs=[file_input("/transfer/in.txt")]), "stages task files"),
        (make_task(volumes=["/transfer"]), "stages task files"),
        (make_task(outputs=[dir_output("/transfer/out")]), "stages task files"),
        (make_task(volumes=["scratch"]), "must be absolute"),
    ],
)
def test_paths_that_cannot_be_mounted_are_rejected(task: TesTask, message: str):
    with pytest.raises(ValueError, match=message):
        build_taskpod_job(task, CONFIG)


def test_transfer_prefix_is_compared_by_component():
    # `/transferx` is not the staging directory
    task = make_task(outputs=[file_output("/transferx/out.txt")])

    assert path_mounts(task) == {"/transferx": "transferx"}
