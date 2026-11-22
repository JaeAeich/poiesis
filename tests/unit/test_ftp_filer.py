"""Tests for FTP inputs and outputs, staged by `FtpFilerStrategy`.

Transfers go to a real FTP server (pyftpdlib) in a thread, with an
anonymous area, as public archives have, and a user with a password.
"""

from __future__ import annotations

import asyncio
import ftplib
import logging
import socket
import ssl
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

from poiesis.api.settings import Settings
from poiesis.tes.models import (
    TesExecutor,
    TesFileType,
    TesInput,
    TesOutput,
    TesTask,
)
from poiesis.core import filer_error
from poiesis.core.constants import FTP_ENABLED_ENV
from poiesis.core.filer import filer_strategy_factory as factory
from poiesis.core.filer.strategy import filer_strategy, ftp_filer
from poiesis.core.filer.strategy.filer_strategy import redact_url
from poiesis.core.filer.strategy.ftp_filer import FtpError
from poiesis.core.filer.tif import Tif
from poiesis.core.filer.tof import Tof
from poiesis.core.taskpod import RuntimeConfig, build_taskpod_job

PASSWORD = "s3cret-pass"  # noqa: S105 - a test login


@dataclass
class Ftp:
    """The running server: its address and the directories it serves."""

    port: int
    public: Path
    home: Path

    def url(self, path: str, *, login: str = "") -> str:
        return f"ftp://{login}127.0.0.1:{self.port}/{path}"

    def user_url(self, path: str, password: str = PASSWORD) -> str:
        return self.url(path, login=f"alice:{password}@")


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Ftp]:
    """An FTP server: anonymous read in `public`, alice read-write in `home`."""
    public = tmp_path / "public"
    home = tmp_path / "home"
    public.mkdir()
    home.mkdir()
    authorizer = DummyAuthorizer()
    authorizer.add_anonymous(str(public))
    authorizer.add_user("alice", PASSWORD, str(home), perm="elradfmwMT")
    handler = type("Handler", (FTPHandler,), {"authorizer": authorizer})
    logging.getLogger("pyftpdlib").setLevel(logging.WARNING)
    ftpd = FTPServer(("127.0.0.1", 0), handler)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            ftpd.serve_forever(timeout=0.05, blocking=False, handle_exit=False)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield Ftp(ftpd.socket.getsockname()[1], public, home)
    finally:
        stop.set()
        thread.join(5)
        ftpd.close_all()


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The task volume as TIF/TOF see it."""
    path = tmp_path / "pvc"
    path.mkdir()
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(path))
    return path


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Delays between retries, recorded instead of slept."""
    delays: list[float] = []
    monkeypatch.setattr(ftp_filer.time, "sleep", delays.append)
    return delays


def stage(url: str, path: str, kind: TesFileType = TesFileType.FILE) -> None:
    asyncio.run(Tif("task", [TesInput(url=url, path=path, type=kind)]).transfer())


def test_anonymous_file_is_downloaded(server: Ftp, pvc: Path) -> None:
    (server.public / "pub").mkdir()
    (server.public / "pub" / "genome.fa").write_bytes(b">chr1\nACGT\n" * 1000)
    stage(server.url("pub/genome.fa"), "/in/genome.fa")
    assert (pvc / "in" / "genome.fa").read_bytes() == b">chr1\nACGT\n" * 1000
    assert [p.name for p in (pvc / "in").iterdir()] == ["genome.fa"]


def test_user_file_is_downloaded_with_the_login(server: Ftp, pvc: Path) -> None:
    (server.home / "private.txt").write_text("mine")
    stage(server.user_url("private.txt"), "/in/private.txt")
    assert (pvc / "in" / "private.txt").read_text() == "mine"


def test_directory_is_downloaded_recursively(server: Ftp, pvc: Path) -> None:
    run = server.public / "run1"
    (run / "lane" / "deep").mkdir(parents=True)
    (run / "a.fastq").write_text("a")
    (run / "lane" / "b.fastq").write_text("b")
    (run / "lane" / "deep" / "c.fastq").write_text("c")
    (run / "empty").mkdir()
    stage(server.url("run1"), "/in/run1", TesFileType.DIRECTORY)
    staged = pvc / "in" / "run1"
    assert (staged / "a.fastq").read_text() == "a"
    assert (staged / "lane" / "b.fastq").read_text() == "b"
    assert (staged / "lane" / "deep" / "c.fastq").read_text() == "c"
    assert (staged / "empty").is_dir()


def test_file_given_as_a_directory_fails(server: Ftp, pvc: Path) -> None:
    (server.public / "x.txt").write_text("x")
    with pytest.raises(FtpError, match="not a directory"):
        stage(server.url("x.txt"), "/in/x", TesFileType.DIRECTORY)


class ListingFtp:
    """Stands in for an `ftplib.FTP` whose server lists hostile names."""

    def __init__(self, *, mlsd: bool) -> None:
        self.has_mlsd = mlsd
        self.dirs = {"d"}

    def mlsd(self, path, facts=()):
        if not self.has_mlsd:
            raise ftplib.error_perm("500 MLSD not understood")
        return iter(
            [
                (".", {"type": "cdir"}),
                ("..", {"type": "pdir"}),
                ("../../escape", {"type": "file"}),
                ("ok", {"type": "file"}),
            ]
        )

    def nlst(self, *args):
        return ["d/.", "d/..", "d/../../escape", "d/ok", "/abs/sub"]

    def pwd(self):
        return "/"

    def cwd(self, path):
        if path not in ("/", *self.dirs):
            raise ftplib.error_perm("550 not a directory")


@pytest.mark.parametrize("mlsd", [True, False])
def test_listing_cannot_lead_outside_the_directory(mlsd: bool) -> None:
    names = [name for name, _ in ftp_filer._list(ListingFtp(mlsd=mlsd), "d")]
    assert ".." not in names
    assert "." not in names
    assert all("/" not in name for name in names)
    assert "escape" in names
    assert "ok" in names


def test_missing_file_fails_at_once_with_the_reply(
    server: Ftp, pvc: Path, sleeps: list[float]
) -> None:
    with pytest.raises(FtpError, match="550") as caught:
        stage(server.url("pub/missing.fa"), "/in/missing.fa")
    assert sleeps == []
    assert "/pub/missing.fa" in str(caught.value)
    assert not list((pvc / "in").iterdir())


def test_wrong_password_fails_without_showing_it(
    server: Ftp, pvc: Path, sleeps: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    (server.home / "private.txt").write_text("mine")
    url = server.user_url("private.txt", password="wrong-password")
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(FtpError, match="login .* was refused: 530") as caught,
    ):
        stage(url, "/in/private.txt")
    assert sleeps == []
    cause = filer_error.describe(caught.value)
    assert "input /in/private.txt" in cause
    for text in (str(caught.value), cause, caplog.text):
        assert "wrong-password" not in text
        assert "alice" not in text


def test_refused_connection_is_retried(
    pvc: Path, sleeps: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    url = f"ftp://alice:{PASSWORD}@127.0.0.1:{free_port()}/x"
    with caplog.at_level(logging.DEBUG), pytest.raises(ConnectionRefusedError):
        stage(url, "/in/x")
    assert sleeps == [1, 2]
    assert PASSWORD not in caplog.text


def free_port() -> int:
    """A local port nothing listens on."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_transient_reply_is_retried(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    calls: list[int] = []

    def run(ftp: object) -> None:
        calls.append(1)
        if len(calls) < 3:  # noqa: PLR2004
            raise ftplib.error_temp("421 too many connections")

    monkeypatch.setattr(ftp_filer, "_session", _NoSession)
    ftp_filer._with_session("ftp://h/x", "download", run)
    assert len(calls) == 3  # noqa: PLR2004
    assert sleeps == [1, 2]


class _NoSession:
    def __init__(self, url: str) -> None:
        pass

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> None:
        return None


def test_ftps_checks_the_certificate(
    monkeypatch: pytest.MonkeyPatch, pvc: Path, sleeps: list[float]
) -> None:
    contexts: list[ssl.SSLContext] = []

    class Tls(ftplib.FTP_TLS):
        def __init__(self, *args, context=None, **kwargs) -> None:
            contexts.append(context)
            super().__init__(*args, context=context, **kwargs)

        def connect(self, *args, **kwargs):
            raise ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(ftp_filer.ftplib, "FTP_TLS", Tls)
    with pytest.raises(ssl.SSLCertVerificationError):
        stage("ftps://archive.example.org/x", "/in/x")
    assert sleeps == []
    assert contexts[0].verify_mode is ssl.CERT_REQUIRED
    assert contexts[0].check_hostname


def upload(output: TesOutput) -> list[str]:
    uploaded: list[str] = []

    async def record(files) -> None:
        uploaded.extend(f.url for f in files)

    asyncio.run(Tof("task", [output], record).transfer())
    return uploaded


def test_file_is_uploaded_and_logged_without_the_login(server: Ftp, pvc: Path) -> None:
    (pvc / "out").mkdir()
    (pvc / "out" / "result.vcf").write_text("##fileformat=VCFv4.2\n")
    urls = upload(
        TesOutput(url=server.user_url("runs/1/result.vcf"), path="/out/result.vcf")
    )
    assert (server.home / "runs" / "1" / "result.vcf").read_text().startswith("##")
    assert urls == [server.url("runs/1/result.vcf")]


def test_directory_is_uploaded(server: Ftp, pvc: Path) -> None:
    (pvc / "out" / "res" / "sub").mkdir(parents=True)
    (pvc / "out" / "res" / "a.txt").write_text("a")
    (pvc / "out" / "res" / "sub" / "b.txt").write_text("b")
    urls = upload(
        TesOutput(
            url=server.user_url("dest"), path="/out/res", type=TesFileType.DIRECTORY
        )
    )
    assert (server.home / "dest" / "a.txt").read_text() == "a"
    assert (server.home / "dest" / "sub" / "b.txt").read_text() == "b"
    assert sorted(urls) == [server.url("dest/a.txt"), server.url("dest/sub/b.txt")]


def test_glob_is_uploaded(server: Ftp, pvc: Path) -> None:
    (pvc / "out").mkdir()
    for name in ("s1.vcf", "s2.vcf", "notes.txt"):
        (pvc / "out" / name).write_text(name)
    upload(TesOutput(url=server.user_url("vcf"), path="/out/*.vcf", path_prefix="/out"))
    assert sorted(p.name for p in (server.home / "vcf").iterdir()) == [
        "s1.vcf",
        "s2.vcf",
    ]


def test_upload_refused_by_the_server_fails(server: Ftp, pvc: Path) -> None:
    (pvc / "out").mkdir()
    (pvc / "out" / "x").write_text("x")
    # Anonymous users may only read.
    with pytest.raises(FtpError, match="upload .* refused by the server: 550"):
        upload(TesOutput(url=server.url("x"), path="/out/x"))


def test_missing_output_is_the_users_error(server: Ftp, pvc: Path) -> None:
    with pytest.raises(filer_error.MissingOutputError):
        upload(TesOutput(url=server.user_url("x"), path="/out/never"))


def test_redact_url_drops_the_login() -> None:
    assert redact_url("ftp://alice:pw@host:21/a/b") == "ftp://host:21/a/b"
    assert redact_url("https://u@h/p?sig=1") == "https://h/p"


def test_ftp_is_on_by_default_and_can_be_turned_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FTP_ENABLED_ENV, raising=False)
    for name in ("ftp", "ftps"):
        assert name in factory.supported_input_schemes()
        assert name in factory.supported_output_schemes()
    assert factory.can_input("ftp://ftp.ebi.ac.uk/pub/x")
    assert factory.can_output("ftps://h/out/")

    monkeypatch.setenv(FTP_ENABLED_ENV, "false")
    assert "ftp" not in factory.supported_input_schemes()
    assert "ftps" not in factory.supported_output_schemes()
    assert not factory.can_input("ftp://ftp.ebi.ac.uk/pub/x")
    config = RuntimeConfig(taskpod_namespace="po", poiesis_image="img")
    with pytest.raises(ValueError, match=r"inputs\[0\].url .* FTP turned off"):
        build_taskpod_job(_task(TesInput(url="ftp://h/x", path="/in/x")), config)
    with pytest.raises(ValueError, match=r"outputs\[0\].url .* FTP turned off"):
        build_taskpod_job(
            _task(outputs=[TesOutput(url="ftps://h/x", path="/out/x")]), config
        )


def test_ftp_directory_input_is_accepted() -> None:
    config = RuntimeConfig(taskpod_namespace="po", poiesis_image="img")
    build_taskpod_job(
        _task(TesInput(url="ftp://h/d", path="/in/d", type=TesFileType.DIRECTORY)),
        config,
    )


def test_turning_ftp_off_reaches_the_filers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FTP_ENABLED_ENV, "false")
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    config = Settings().runtime_config()
    assert not config.ftp_enabled
    _pvc, job = build_taskpod_job(_task(), config)
    for container in job.spec.template.spec.init_containers:
        env = {e.name: e.value for e in container.env or []}
        if container.name in ("tif", "tof"):
            assert env[FTP_ENABLED_ENV] == "false"
        else:
            assert FTP_ENABLED_ENV not in env


def test_ftp_switch_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FTP_ENABLED_ENV, "maybe")
    monkeypatch.setenv("POIESIS_AUTH_ENABLED", "false")
    with pytest.raises(ValueError, match=FTP_ENABLED_ENV):
        Settings()


def _task(*inputs: TesInput, outputs: list[TesOutput] | None = None) -> TesTask:
    return TesTask(
        id="11111111-1111-1111-1111-111111111111",
        executors=[TesExecutor(image="alpine", command=["true"])],
        inputs=list(inputs),
        outputs=outputs or [],
    )
