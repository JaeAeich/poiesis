"""`file://` URLs are off unless the operator names roots; outputs stay on the volume.

TIF and TOF hold the service's credentials. A `file://` URL, or a symlink
left on the task volume, must not let a task read files from their
containers.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from poiesis.api.settings import Settings
from poiesis.api.tes.models import TesExecutor, TesInput, TesOutput, TesTask
from poiesis.core.constants import FILE_URL_ROOTS_ENV
from poiesis.core.services.filer import filer_strategy_factory as factory
from poiesis.core.services.filer.file_urls import (
    file_url_allowed,
    parse_file_url_roots,
    resolve_file_url,
)
from poiesis.core.services.filer.strategy import filer_strategy
from poiesis.core.services.filer.tif import Tif
from poiesis.core.services.filer.tof import Tof
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job


@pytest.fixture
def volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The task volume as TIF/TOF see it."""
    path = tmp_path / "pvc"
    path.mkdir()
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(path))
    return path


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An operator-allowed directory."""
    path = tmp_path / "reference"
    path.mkdir()
    monkeypatch.setenv(FILE_URL_ROOTS_ENV, str(path))
    return path


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    """A file in the filer container the task must never see."""
    path = tmp_path / "environ"
    path.write_text("DATABASE_URL=postgres://secret")
    return path


def test_file_scheme_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FILE_URL_ROOTS_ENV, raising=False)
    assert not factory.can_input("file:///proc/self/environ")
    assert not factory.can_output("file:///tmp/out")
    assert "file" not in factory.supported_input_schemes()
    assert "file" not in factory.supported_output_schemes()
    with pytest.raises(ValueError, match="Unsupported"):
        factory.create_input_strategy(
            "file:///etc/passwd", TesInput(url="file:///etc/passwd", path="/in/p")
        )


def test_only_paths_under_a_root_are_accepted(root: Path) -> None:
    assert factory.can_input(f"file://{root}/genome.fa")
    assert factory.can_output(f"file://{root}/out/")
    assert "file" in factory.supported_input_schemes()
    for refused in (
        "file:///proc/self/environ",
        f"file://{root}/../environ",
        f"file://{root}-other/x",
        f"file://otherhost{root}/x",
        "file://",
    ):
        assert not file_url_allowed(refused), refused
        assert not factory.can_input(refused), refused


def test_symlink_under_a_root_cannot_leave_it(root: Path, secret: Path) -> None:
    (root / "link").symlink_to(secret)
    with pytest.raises(PermissionError, match="resolves outside"):
        resolve_file_url(f"file://{root}/link")
    assert resolve_file_url(f"file://{root}/genome.fa").endswith("/genome.fa")


def test_tif_refuses_a_file_url_when_the_scheme_is_off(
    volume: Path, secret: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FILE_URL_ROOTS_ENV, raising=False)
    task_input = TesInput(url=f"file://{secret}", path="/in/environ")
    with pytest.raises(ValueError, match="Unsupported"):
        asyncio.run(Tif("task", [task_input]).file())
    assert not (volume / "in" / "environ").exists()


def test_tif_stages_from_an_allowed_root(volume: Path, root: Path) -> None:
    (root / "genome.fa").write_text(">chr1")
    task_input = TesInput(url=f"file://{root}/genome.fa", path="/in/genome.fa")
    asyncio.run(Tif("task", [task_input]).file())
    assert (volume / "in" / "genome.fa").read_text() == ">chr1"


@pytest.mark.parametrize(
    ("layout", "path", "prefix"),
    [
        ("file", "/work/out/leak", None),
        ("glob", "/work/out/*", "/work/out/"),
        ("dir", "/work/out", None),
        ("nested", "/work/out", None),
    ],
)
def test_tof_refuses_outputs_that_link_outside_the_volume(
    volume: Path,
    root: Path,
    secret: Path,
    layout: str,
    path: str,
    prefix: str | None,
) -> None:
    out = volume / "work" / "out"
    out.mkdir(parents=True)
    if layout == "nested":
        (out / "sub").mkdir()
        (out / "sub" / "leak").symlink_to(secret)
    elif layout == "dir":
        (out / "leakdir").symlink_to(secret.parent, target_is_directory=True)
    else:
        (out / "leak").symlink_to(secret)
    output = TesOutput(
        url=f"file://{root}/dest",
        path=path,
        path_prefix=prefix,
        type="DIRECTORY" if layout in ("dir", "nested") else "FILE",
    )
    with pytest.raises(PermissionError, match="outside the task volume"):
        asyncio.run(Tof("task", [output]).file())
    assert not list(root.rglob("*"))


def test_tof_uploads_links_that_stay_on_the_volume(volume: Path, root: Path) -> None:
    out = volume / "work" / "out"
    out.mkdir(parents=True)
    (out / "real.txt").write_text("data")
    (out / "alias.txt").symlink_to(out / "real.txt")
    output = TesOutput(url=f"file://{root}/dest", path="/work/out", type="DIRECTORY")
    asyncio.run(Tof("task", [output]).file())
    assert (root / "dest" / "alias.txt").read_text() == "data"


@pytest.mark.parametrize("raw", ["/", "relative/path", "/ok,/"])
def test_bad_roots_are_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="POIESIS_FILE_URL_ROOTS"):
        parse_file_url_roots(raw)


def test_roots_are_normalised_and_deduplicated() -> None:
    assert parse_file_url_roots(" /mnt/ref/ ,/mnt/ref,, /data ") == (
        "/mnt/ref",
        "/data",
    )


def _task(url: str) -> TesTask:
    return TesTask(
        id="11111111-1111-1111-1111-111111111111",
        executors=[TesExecutor(image="alpine", command=["true"])],
        inputs=[TesInput(url=url, path="/in/x")],
    )


def test_api_rejects_file_urls_and_passes_roots_to_filers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FILE_URL_ROOTS_ENV, raising=False)
    off = RuntimeConfig(taskpod_namespace="po", poiesis_image="img")
    with pytest.raises(ValueError, match="not supported as a TES input"):
        build_taskpod_job(_task("file:///proc/self/environ"), off)

    monkeypatch.setenv(FILE_URL_ROOTS_ENV, "/mnt/ref")
    on = RuntimeConfig(
        taskpod_namespace="po", poiesis_image="img", file_url_roots=("/mnt/ref",)
    )
    with pytest.raises(ValueError, match="not supported as a TES input"):
        build_taskpod_job(_task("file:///proc/self/environ"), on)
    _pvc, job = build_taskpod_job(_task("file:///mnt/ref/x"), on)
    containers = job.spec.template.spec.init_containers
    tif = next(c for c in containers if c.name == "tif")
    assert {e.name: e.value for e in tif.env}[FILE_URL_ROOTS_ENV] == "/mnt/ref"
    for container in containers:
        if container.name.startswith("exec-"):
            assert FILE_URL_ROOTS_ENV not in {e.name for e in container.env or []}


def test_settings_read_the_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FILE_URL_ROOTS_ENV, "/mnt/ref,/data")
    assert Settings.model_fields["file_url_roots"].default_factory() == (
        "/mnt/ref",
        "/data",
    )
