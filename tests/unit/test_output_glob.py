"""An output glob that matches no file uploads nothing by default (#106).

It used to upload everything under the output's `path_prefix`. That is now
an operator setting, `taskpods.outputGlobFallback`, off by default, which
reaches TOF as `POIESIS_OUTPUT_GLOB_FALLBACK`.
"""

import asyncio
import logging
from pathlib import Path

import pytest

from poiesis.api.settings import AuthSettings, Settings
from poiesis.api.tes.models import TesExecutor, TesOutput, TesTask
from poiesis.core.constants import FILE_URL_ROOTS_ENV, OUTPUT_GLOB_FALLBACK_ENV
from poiesis.core.services.filer.strategy import filer_strategy
from poiesis.core.services.filer.tof import Tof
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

GLOB = "/outputs/*.vcf"


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The task's volume, holding only `/outputs/a.txt`, as in the issue."""
    volume = tmp_path / "pvc"
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(volume))
    (volume / "outputs").mkdir(parents=True)
    (volume / "outputs" / "a.txt").write_text("a")
    return volume


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    """Where a `file://` output uploads to."""
    return tmp_path / "dest" / "run1"


@pytest.fixture(autouse=True)
def _logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """Let caplog see filer logs, and start with the fallback unset."""
    # poiesis.core doesn't propagate to the root logger, where caplog listens.
    monkeypatch.setattr(logging.getLogger("poiesis.core"), "propagate", True)
    caplog.set_level(logging.INFO)
    monkeypatch.delenv(OUTPUT_GLOB_FALLBACK_ENV, raising=False)
    monkeypatch.setenv(FILE_URL_ROOTS_ENV, str(tmp_path))


def run_tof(dest: Path, path: str = GLOB) -> None:
    """Upload one output to `dest`, as TOF does."""
    output = TesOutput(url=f"file://{dest}", path=path, path_prefix="/outputs/")
    asyncio.run(Tof("task", [output]).transfer())


def uploaded(dest: Path) -> list[str]:
    """The files under `dest`, relative to it."""
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())


def test_no_match_uploads_nothing_and_warns(pvc, dest, caplog):
    """A glob that matches nothing uploads nothing; a warning names it."""
    run_tof(dest)
    assert not dest.exists()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert GLOB in warnings[0].getMessage()
    assert "nothing uploaded" in warnings[0].getMessage()


def test_fallback_on_uploads_path_prefix(pvc, dest, caplog, monkeypatch):
    """With the fallback on, a glob that matches nothing uploads path_prefix."""
    monkeypatch.setenv(OUTPUT_GLOB_FALLBACK_ENV, "true")
    run_tof(dest)
    assert uploaded(dest) == ["a.txt"]
    assert "falling back to uploading parent directory" in caplog.text


@pytest.mark.parametrize("fallback", ["", "true"])
def test_match_uploads_only_matches(pvc, dest, caplog, monkeypatch, fallback):
    """A glob that matches uploads the matches, whatever the setting."""
    monkeypatch.setenv(OUTPUT_GLOB_FALLBACK_ENV, fallback)
    (pvc / "outputs" / "b.vcf").write_text("b")
    run_tof(dest)
    assert uploaded(dest) == ["b.vcf"]
    assert "matched no files" not in caplog.text


@pytest.mark.parametrize(
    ("value", "enabled"), [("", False), ("false", False), ("true", True)]
)
def test_settings(monkeypatch, value, enabled):
    """`POIESIS_OUTPUT_GLOB_FALLBACK` is off unless set to true."""
    monkeypatch.setenv(OUTPUT_GLOB_FALLBACK_ENV, value)
    settings = Settings(auth=AuthSettings(enabled=False))
    assert settings.output_glob_fallback is enabled
    assert settings.runtime_config().output_glob_fallback is enabled


def test_settings_typo_refused(monkeypatch):
    """A misspelled value fails startup rather than guessing."""
    monkeypatch.setenv(OUTPUT_GLOB_FALLBACK_ENV, "yes please")
    with pytest.raises(ValueError, match=OUTPUT_GLOB_FALLBACK_ENV):
        Settings(auth=AuthSettings(enabled=False))


def filer_env(config: RuntimeConfig) -> dict[str, dict[str, str | None]]:
    """Each poiesis container's value of the fallback env var, by name."""
    task = TesTask(
        id="t1",
        executors=[TesExecutor(image="busybox:1.36", command=["true"])],
        outputs=[TesOutput(url="s3://bucket/out", path=GLOB)],
    )
    _, job = build_taskpod_job(task, config)
    containers = job.spec.template.spec.init_containers
    return {
        c.name: {
            e.name: e.value for e in c.env or [] if e.name == OUTPUT_GLOB_FALLBACK_ENV
        }
        for c in containers
    }


@pytest.mark.parametrize("enabled", [False, True])
def test_setting_reaches_tof(enabled):
    """TOF gets the env var only when the fallback is on."""
    config = RuntimeConfig(
        taskpod_namespace="tasks",
        poiesis_image="poiesis:test",
        output_glob_fallback=enabled,
    )
    expected = {OUTPUT_GLOB_FALLBACK_ENV: "true"} if enabled else {}
    assert filer_env(config)["tof"] == expected


def test_missing_plain_path_with_prefix_fails(pvc, dest):
    """A plain path that doesn't exist fails, with or without `path_prefix`."""
    with pytest.raises(FileNotFoundError):
        run_tof(dest, "/outputs/missing.txt")
    assert not dest.exists()
