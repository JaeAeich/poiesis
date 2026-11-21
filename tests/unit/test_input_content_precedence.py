"""An input with both `content` and `url` stages its content (#166).

TES: "If content is not empty, "url" must be ignored." TIF used the URL.
"""

import asyncio
from pathlib import Path

import pytest

from poiesis.api.tes.models import TesExecutor, TesInput, TesTask
from poiesis.core.constants import FILE_URL_ROOTS_ENV
from poiesis.core.services.filer.strategy import filer_strategy
from poiesis.core.services.filer.tif import Tif
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

CONFIG = RuntimeConfig(taskpod_namespace="poiesis", poiesis_image="poiesis:test")


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temporary directory standing in for the task's volume."""
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(tmp_path))
    return tmp_path


def test_content_wins_over_url(pvc):
    """The content is staged; the URL, which would fail, isn't fetched."""
    tes_input = TesInput(path="/in/a.txt", url="ftp://nowhere/x", content="hello")
    asyncio.run(Tif("task", [tes_input]).file())
    assert (pvc / "in" / "a.txt").read_text() == "hello"


def test_empty_content_uses_the_url(pvc, tmp_path, monkeypatch):
    """Only content that is not empty overrides the URL."""
    monkeypatch.setenv(FILE_URL_ROOTS_ENV, str(tmp_path))
    source = tmp_path / "src.txt"
    source.write_text("from url")
    tes_input = TesInput(path="/in/a.txt", url=f"file://{source}", content="")
    asyncio.run(Tif("task", [tes_input]).file())
    assert (pvc / "in" / "a.txt").read_text() == "from url"


def test_url_of_a_content_input_is_not_validated():
    """An unsupported URL next to content is ignored, not refused."""
    task = TesTask(
        id="t",
        executors=[TesExecutor(image="busybox", command=["true"])],
        inputs=[TesInput(path="/in/a.txt", url="ftp://nowhere/x", content="hello")],
    )
    build_taskpod_job(task, CONFIG)
