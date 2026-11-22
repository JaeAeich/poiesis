"""TOF records each uploaded file in `logs[].outputs` (#166).

One entry per file, with its path in the executor, its size, and the URL
it was uploaded to, without the query. A DIRECTORY or glob output gives
one entry per file under it.
"""

import asyncio
import io
from pathlib import Path
from typing import Any

import pytest
import requests

from poiesis.tes.models import TesFileType, TesOutput, TesOutputFileLog
from poiesis.core.constants import FILE_URL_ROOTS_ENV
from poiesis.core.filer.filer_strategy_factory import create_output_strategy
from obstore.store import MemoryStore

from poiesis.core.filer.strategy import (
    filer_strategy,
    http_filer,
    object_store_filer,
)
from poiesis.core.filer.tof import Tof


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The task's volume with a file, a directory and files for a glob."""
    volume = tmp_path / "pvc"
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(volume))
    for path, data in {
        "out/a.txt": b"abc",
        "out/dir/x": b"x",
        "out/dir/sub/y": b"yy",
        "out/glob/1.vcf": b"1",
        "out/glob/2.vcf": b"22",
        "out/glob/skip.txt": b"",
    }.items():
        file = volume / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    return volume


@pytest.fixture
def puts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Answer every PUT with 200; return the URLs sent to."""
    urls: list[str] = []

    def request(method: str, url: str, **_: object) -> requests.Response:
        assert method == "PUT"
        urls.append(url)
        response = requests.Response()
        response.status_code = 200
        response.raw = io.BytesIO(b"")
        return response

    monkeypatch.setattr(http_filer.requests, "request", request)
    return urls


def upload(output: TesOutput) -> list[tuple[str, str, str]]:
    """Upload `output` as TOF does; return its `(path, size, url)` entries."""
    strategy = create_output_strategy(output.url, output)
    asyncio.run(strategy.upload())
    return sorted((o.path, o.size_bytes, o.url) for o in strategy.uploaded)


SIGNED = "?X-Amz-Signature=secret"


def test_http_file_is_recorded_without_the_query(pvc, puts):
    """A presigned URL is stored without its signature."""
    entries = upload(TesOutput(url=f"https://h/b/a.txt{SIGNED}", path="/out/a.txt"))
    assert entries == [("/out/a.txt", "3", "https://h/b/a.txt")]
    assert puts == [f"https://h/b/a.txt{SIGNED}"]


def test_http_directory_gives_one_entry_per_file(pvc, puts):
    """Directory outputs are flattened into separate items."""
    output = TesOutput(
        url=f"https://h/b/dir{SIGNED}", path="/out/dir", type=TesFileType.DIRECTORY
    )
    assert upload(output) == [
        ("/out/dir/sub/y", "2", "https://h/b/dir/sub/y"),
        ("/out/dir/x", "1", "https://h/b/dir/x"),
    ]


def test_http_glob_gives_one_entry_per_match(pvc, puts):
    """Each match is logged at the URL built from `path_prefix`."""
    output = TesOutput(url="https://h/b/g", path="/out/glob/*.vcf", path_prefix="/out")
    assert upload(output) == [
        ("/out/glob/1.vcf", "1", "https://h/b/g/glob/1.vcf"),
        ("/out/glob/2.vcf", "2", "https://h/b/g/glob/2.vcf"),
    ]


def test_file_url_outputs_are_recorded(pvc, tmp_path, monkeypatch):
    """`file://` outputs log the file each one was copied to."""
    monkeypatch.setenv(FILE_URL_ROOTS_ENV, str(tmp_path))
    dest = tmp_path / "dest"
    dest.mkdir()
    real = dest.resolve()
    assert upload(TesOutput(url=f"file://{dest}/a.txt", path="/out/a.txt")) == [
        ("/out/a.txt", "3", f"file://{real}/a.txt")
    ]
    output = TesOutput(
        url=f"file://{dest}/d", path="/out/dir", type=TesFileType.DIRECTORY
    )
    assert upload(output) == [
        ("/out/dir/sub/y", "2", f"file://{real}/d/sub/y"),
        ("/out/dir/x", "1", f"file://{real}/d/x"),
    ]
    glob = TesOutput(
        url=f"file://{dest}/g", path="/out/glob/*.vcf", path_prefix="/out/glob"
    )
    assert upload(glob) == [
        ("/out/glob/1.vcf", "1", f"file://{real}/g/1.vcf"),
        ("/out/glob/2.vcf", "2", f"file://{real}/g/2.vcf"),
    ]


def test_s3_outputs_are_recorded(pvc, monkeypatch):
    """S3 entries name the object each file was uploaded to."""
    store = MemoryStore()
    monkeypatch.setattr(object_store_filer, "make_store", lambda _location: store)
    assert upload(TesOutput(url="s3://b/k/a.txt", path="/out/a.txt")) == [
        ("/out/a.txt", "3", "s3://b/k/a.txt")
    ]
    output = TesOutput(url="s3://b/d", path="/out/dir", type=TesFileType.DIRECTORY)
    assert upload(output) == [
        ("/out/dir/sub/y", "2", "s3://b/d/sub/y"),
        ("/out/dir/x", "1", "s3://b/d/x"),
    ]
    glob = TesOutput(url="s3://b/g", path="/out/glob/*.vcf", path_prefix="/out/glob")
    assert upload(glob) == [
        ("/out/glob/1.vcf", "1", "s3://b/g/1.vcf"),
        ("/out/glob/2.vcf", "2", "s3://b/g/2.vcf"),
    ]


def test_tof_records_every_output_once_uploaded(pvc, puts):
    """The entries of every output are stored in one call, after the uploads."""
    stored: list[list[TesOutputFileLog]] = []

    async def record(files: list[TesOutputFileLog]) -> None:
        assert len(puts) == 3
        stored.append(files)

    outputs = [
        TesOutput(url="https://h/a", path="/out/a.txt"),
        TesOutput(url="https://h/d", path="/out/dir", type=TesFileType.DIRECTORY),
    ]
    asyncio.run(Tof("task", outputs, record).transfer())
    (files,) = stored
    assert sorted(f.path for f in files) == [
        "/out/a.txt",
        "/out/dir/sub/y",
        "/out/dir/x",
    ]


def test_failure_to_record_fails_tof(pvc, puts):
    """A failed write is not swallowed: TOF fails and says why."""

    async def record(_files: Any) -> None:
        raise ConnectionRefusedError("database down")

    tof = Tof("task", [TesOutput(url="https://h/a", path="/out/a.txt")], record)
    with pytest.raises(ConnectionRefusedError) as error:
        asyncio.run(tof.transfer())
    assert "recording the output file logs in the database" in (error.value.__notes__)
