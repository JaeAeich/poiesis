"""One object-store strategy for `s3://`, `gs://` and `az://` (#162).

Runs against obstore's in-memory store: no network. The path mapping for
files, DIRECTORY outputs and globs is the one the S3 strategy had; the S3
edge cases of the issue are fixed: folder markers, a DIRECTORY input that
matches nothing, keys with glob characters, keys that leave the target.
"""

import asyncio
from datetime import timedelta
from pathlib import Path

import obstore
import pytest
from obstore.store import AzureStore, GCSStore, MemoryStore, S3Store

from poiesis.tes.models import TesFileType, TesInput, TesOutput
from poiesis.core import filer_error
from poiesis.core.constants import (
    S3_REQUESTER_PAYS_ENV,
    S3_SERVER_SIDE_ENCRYPTION_ENV,
    S3_SSE_KMS_KEY_ID_ENV,
    S3_VIRTUAL_HOSTED_STYLE_ENV,
)
from poiesis.core.filer.filer_strategy_factory import (
    create_input_strategy,
    create_output_strategy,
)
from poiesis.core.filer.strategy import filer_strategy, object_store_filer
from poiesis.core.filer.strategy.object_store_filer import (
    MAX_PARALLEL_TRANSFERS,
    ObjectStoreError,
    ObjectStoreFilerStrategy,
    ObjectUrl,
    glob_base,
    make_store,
    parse_object_url,
    plan_directory_download,
    run_bounded,
)
from poiesis.core.filer.tif import Tif
from poiesis.core.filer.tof import Tof

SCHEMES = ["s3", "gs", "az"]


@pytest.fixture
def pvc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The task's volume."""
    volume = tmp_path / "pvc"
    volume.mkdir()
    monkeypatch.setattr(filer_strategy, "FILER_PVC_PATH", str(volume))
    return volume


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    """One in-memory bucket that every object-store URL resolves to."""
    memory = MemoryStore()
    monkeypatch.setattr(object_store_filer, "make_store", lambda _location: memory)
    return memory


def put(store: MemoryStore, objects: dict[str, bytes]) -> None:
    """Store each key → body in `store`."""
    for key, body in objects.items():
        obstore.put(store, key, body)


def keys(store: MemoryStore) -> dict[str, bytes]:
    """Every key in `store` with its body."""
    found = [meta["path"] for chunk in obstore.list(store) for meta in chunk]
    return {key: bytes(obstore.get(store, key).bytes()) for key in sorted(found)}


def files(root: Path) -> dict[str, bytes]:
    """Every file under `root`, relative to it, with its content."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def upload(output: TesOutput) -> list[tuple[str, str, str]]:
    """Upload `output` as TOF does; return its `(path, size, url)` entries."""
    strategy = create_output_strategy(output.url, output)
    asyncio.run(strategy.upload())
    return [(o.path, o.size_bytes, o.url) for o in strategy.uploaded]


def download(tes_input: TesInput) -> None:
    """Stage `tes_input` as TIF does."""
    asyncio.run(create_input_strategy(tes_input.url, tes_input).download())


# --- URLs -------------------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_every_scheme_gets_the_object_store_strategy(scheme: str, store) -> None:
    """`s3://`, `gs://` and `az://` share one strategy."""
    url = f"{scheme}://bucket/key"
    strategy = create_input_strategy(url, TesInput(url=url, path="/data/x"))
    assert isinstance(strategy, ObjectStoreFilerStrategy)
    assert strategy.location == ObjectUrl(scheme, "bucket", "key")


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("s3://b/plain/key.txt", "plain/key.txt"),
        ("s3://b/reads[1].fq", "reads[1].fq"),
        ("s3://b/what?.txt", "what?.txt"),
        ("s3://b/x?y=1#z", "x?y=1#z"),
        ("S3://b/{a,b}.txt", "{a,b}.txt"),
        ("gs://b/", ""),
        ("az://container", ""),
    ],
)
def test_url_key_is_taken_as_written(url: str, key: str) -> None:
    """`?`, `#` and glob characters are part of the key, not cut from it."""
    assert parse_object_url(url).key == key


@pytest.mark.parametrize("url", ["s3:///key", "ftp://b/k", "s3:b/k"])
def test_url_without_a_bucket_is_refused(url: str) -> None:
    """No bucket, or not an object-store scheme."""
    with pytest.raises(ValueError):  # noqa: PT011 - any of two messages
        parse_object_url(url)


def test_glob_base() -> None:
    """A glob in the output URL keeps the key up to its last `/`."""
    assert glob_base("out/run") == "out/run"
    assert glob_base("out/*.vcf") == "out/"
    assert glob_base("*.vcf") == ""
    assert glob_base("a/b[0-9]/c") == "a/"


# --- Outputs: the path mapping of the S3 strategy ---------------------------


@pytest.fixture
def outputs(pvc: Path) -> Path:
    """A file, a directory and files for a glob, on the volume."""
    for path, data in {
        "out/a.txt": b"abc",
        "out/dir/x": b"x",
        "out/dir/sub/y": b"yy",
        "out/glob/1.vcf": b"1",
        "out/glob/2.vcf": b"22",
        "out/glob/skip.txt": b"",
        "out/glob/more.vcf/z": b"zzz",
    }.items():
        file = pvc / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    return pvc


@pytest.mark.parametrize("scheme", SCHEMES)
def test_file_output(outputs, store, scheme: str) -> None:
    """A FILE goes to the URL's key; its entry names that URL."""
    url = f"{scheme}://b/k/a.txt"
    assert upload(TesOutput(url=url, path="/out/a.txt")) == [("/out/a.txt", "3", url)]
    assert keys(store) == {"k/a.txt": b"abc"}


@pytest.mark.parametrize("url_key", ["d", "d/"])
def test_directory_output(outputs, store, url_key: str) -> None:
    """Each file goes below the URL's key, with or without a trailing `/`."""
    output = TesOutput(
        url=f"s3://b/{url_key}", path="/out/dir", type=TesFileType.DIRECTORY
    )
    assert sorted(upload(output)) == [
        ("/out/dir/sub/y", "2", "s3://b/d/sub/y"),
        ("/out/dir/x", "1", "s3://b/d/x"),
    ]
    assert keys(store) == {"d/sub/y": b"yy", "d/x": b"x"}


def test_directory_output_to_the_bucket_root(outputs, store) -> None:
    """An empty key puts files at the root, not below an empty `/` segment."""
    output = TesOutput(url="s3://b", path="/out/dir", type=TesFileType.DIRECTORY)
    upload(output)
    assert keys(store) == {"sub/y": b"yy", "x": b"x"}


def test_glob_output_with_path_prefix(outputs, store) -> None:
    """A match goes below the URL's key plus its path under `path_prefix`.

    A matched directory goes with everything under it.
    """
    output = TesOutput(url="s3://b/g", path="/out/glob/*.vcf", path_prefix="/out/glob")
    assert sorted(upload(output)) == [
        ("/out/glob/1.vcf", "1", "s3://b/g/1.vcf"),
        ("/out/glob/2.vcf", "2", "s3://b/g/2.vcf"),
        ("/out/glob/more.vcf/z", "3", "s3://b/g/more.vcf/z"),
    ]


def test_glob_output_url_written_as_a_glob(outputs, store) -> None:
    """`s3://b/res/*.vcf` uploads below `res/`, as the S3 strategy did."""
    output = TesOutput(
        url="s3://b/res/*.vcf", path="/out/glob/1.vcf", path_prefix="/out"
    )
    upload(output)
    assert keys(store) == {"res/glob/1.vcf": b"1"}


def test_entries_keep_the_order_of_the_files(outputs, store) -> None:
    """Parallel uploads still give the entries in a fixed order."""
    output = TesOutput(url="s3://b/d", path="/out/dir", type=TesFileType.DIRECTORY)
    assert [path for path, _, _ in upload(output)] == ["/out/dir/x", "/out/dir/sub/y"]


def test_output_key_with_a_question_mark_is_recorded_whole(outputs, store) -> None:
    """An object-store URL has no query, so nothing is cut from the entry."""
    url = "s3://b/what?v=1.txt"
    assert upload(TesOutput(url=url, path="/out/a.txt")) == [("/out/a.txt", "3", url)]
    assert keys(store) == {"what?v=1.txt": b"abc"}


def test_file_output_to_a_prefix_is_refused(outputs, store) -> None:
    """A FILE needs a key; `s3://b/out/` names none."""
    with pytest.raises(ValueError, match="names a prefix"):
        upload(TesOutput(url="s3://b/out/", path="/out/a.txt"))


# --- Inputs ------------------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_file_input(pvc, store, scheme: str) -> None:
    """A FILE input is the object at the URL's key."""
    put(store, {"in/reads.fq": b"ACGT"})
    download(TesInput(url=f"{scheme}://b/in/reads.fq", path="/data/reads.fq"))
    assert files(pvc) == {"data/reads.fq": b"ACGT"}


@pytest.mark.parametrize("key", ["reads[1].fq", "what?.txt", "{a,b}.txt", "s*.fq"])
def test_file_input_key_with_glob_characters(pvc, store, key: str) -> None:
    """The whole key is fetched, not a prefix of it or a pattern."""
    put(store, {f"in/{key}": b"right", "in/other": b"wrong"})
    download(TesInput(url=f"s3://b/in/{key}", path="/data/x"))
    assert files(pvc) == {"data/x": b"right"}


def test_directory_input(pvc, store) -> None:
    """Every object below the key, at its path below the input's path.

    Only whole segments: `in2/` is not below `in`.
    """
    put(
        store,
        {
            "in/a.txt": b"a",
            "in/sub/b[1]?.txt": b"b",
            "in/sub/deeper/c": b"c",
            "in2/not-this": b"x",
        },
    )
    download(TesInput(url="s3://b/in", path="/data/in", type=TesFileType.DIRECTORY))
    assert files(pvc) == {
        "data/in/a.txt": b"a",
        "data/in/sub/b[1]?.txt": b"b",
        "data/in/sub/deeper/c": b"c",
    }


def test_directory_input_matching_nothing_fails(pvc, store) -> None:
    """An empty prefix is an error naming the URL, not a silent success."""
    put(store, {"elsewhere/x": b"x"})
    with pytest.raises(FileNotFoundError, match="s3://b/in matches no object"):
        download(TesInput(url="s3://b/in", path="/data/in", type=TesFileType.DIRECTORY))


def test_folder_markers_are_skipped() -> None:
    """`dir/` keys, and a key that is also a directory of others, are skipped.

    obstore lists the marker `in/sub/` as `in/sub`.
    """
    plan = plan_directory_download(
        "in/",
        ["in/", "in/a", "in/sub/", "in/sub", "in/sub/f", "in/empty/"],
        "/transfer/data",
    )
    assert plan == [("in/a", "/transfer/data/a"), ("in/sub/f", "/transfer/data/sub/f")]


@pytest.mark.parametrize("key", ["in/../escape", "in/sub/../../escape", "in//etc/x"])
def test_key_cannot_leave_the_target(key: str) -> None:
    """A key that would land outside the input's directory is refused.

    `in//etc/x` would be the absolute path `/etc/x` below `in/`.
    """
    with pytest.raises(ValueError, match="leads outside the input directory"):
        plan_directory_download("in", [key], "/transfer/data")


def test_key_cannot_climb_to_a_sibling_with_the_same_prefix() -> None:
    """`../data2` is outside `/transfer/data` though it starts the same."""
    with pytest.raises(ValueError, match="leads outside"):
        plan_directory_download("in", ["in/../data2/x"], "/transfer/data")


# --- Parallel transfers ------------------------------------------------------


def test_transfers_are_bounded() -> None:
    """No more than `MAX_PARALLEL_TRANSFERS` jobs run at once; all run."""
    running = 0
    peak = 0
    done: list[int] = []

    def job(n: int):
        async def run() -> None:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.001)
            running -= 1
            done.append(n)

        return run

    asyncio.run(run_bounded([job(n) for n in range(20)]))
    assert sorted(done) == list(range(20))
    assert peak == MAX_PARALLEL_TRANSFERS


def test_first_failure_is_raised_as_is_and_stops_the_rest() -> None:
    """Not an ExceptionGroup: the filer reports the error itself."""
    started: list[int] = []

    def job(n: int):
        async def run() -> None:
            started.append(n)
            if n == 0:
                raise FileNotFoundError("first")
            await asyncio.sleep(10)

        return run

    with pytest.raises(FileNotFoundError, match="first"):
        asyncio.run(run_bounded([job(n) for n in range(10)]))
    # The failed job's slot may start one more before the rest are cancelled.
    assert len(started) <= MAX_PARALLEL_TRANSFERS + 1


def test_many_files_round_trip(pvc, store) -> None:
    """A directory of many files goes up and comes back intact."""
    source = pvc / "out" / "many"
    expected = {}
    for n in range(25):
        body = f"file {n}\n".encode() * (n + 1)
        (source / f"d{n % 3}").mkdir(parents=True, exist_ok=True)
        (source / f"d{n % 3}" / f"f{n}").write_bytes(body)
        expected[f"d{n % 3}/f{n}"] = body
    upload(TesOutput(url="s3://b/many", path="/out/many", type=TesFileType.DIRECTORY))
    download(TesInput(url="s3://b/many", path="/back", type=TesFileType.DIRECTORY))
    back = {
        k.removeprefix("back/"): v
        for k, v in files(pvc).items()
        if k.startswith("back/")
    }
    assert back == expected


# --- Error causes --------------------------------------------------------------


@pytest.fixture
def message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where the filer writes its termination message."""
    path = tmp_path / "termination-log"
    monkeypatch.setattr(filer_error, "TERMINATION_MESSAGE_PATH", str(path))
    return path


def run(filer: Tif | Tof) -> None:
    """Run `filer` as its CLI does; it exits 1 on failure."""
    with pytest.raises(SystemExit):
        asyncio.run(filer.execute())


def test_missing_input_object_is_reported(message, pvc, store) -> None:
    """The cause names the input and the URL; a system error."""
    run(Tif("task", [TesInput(url="s3://b/missing.fq", path="/data/r.fq")]))
    assert message.read_text() == (
        "input /data/r.fq: FileNotFoundError: GET s3://b/missing.fq: no such object\n"
    )


def test_missing_output_is_the_users_error(message, pvc, store) -> None:
    """An output the executors didn't make is theirs, as before."""
    run(Tof("task", [TesOutput(url="gs://b/out.txt", path="/out/none.txt")]))
    assert message.read_text() == (
        "poiesis-user-error: output /out/none.txt was not produced by the executors\n"
    )


def test_output_symlink_off_the_volume_is_refused(message, pvc, store, tmp_path):
    """TOF does not follow a link out of the volume to upload what it finds."""
    secret = tmp_path / "secret"
    secret.write_text("key")
    (pvc / "out").mkdir()
    (pvc / "out" / "leak").symlink_to(secret)
    run(Tof("task", [TesOutput(url="s3://b/leak", path="/out/leak")]))
    assert "symlink that points outside the task volume" in message.read_text()
    assert keys(store) == {}


def test_unreachable_store_is_one_short_line(message, pvc, monkeypatch) -> None:
    """obstore's debug dump is left out of the cause."""
    unreachable = S3Store(
        "b",
        endpoint="http://127.0.0.1:9",
        access_key_id="id",
        secret_access_key="secret",
        region="us-east-1",
        client_options={"allow_http": True, "connect_timeout": timedelta(seconds=1)},
        retry_config={"max_retries": 0},
    )
    monkeypatch.setattr(object_store_filer, "make_store", lambda _location: unreachable)
    (pvc / "out").mkdir()
    (pvc / "out" / "a").write_text("a")
    run(Tof("task", [TesOutput(url="s3://b/a", path="/out/a")]))
    text = message.read_text()
    assert text.startswith("output /out/a: ObjectStoreError: PUT s3://b/a: ")
    assert "Debug source" not in text
    assert text.count("\n") == 1
    assert issubclass(ObjectStoreError, OSError)


# --- Store configuration -----------------------------------------------------


def test_s3_store_options_from_the_environment(monkeypatch) -> None:
    """Addressing style, SSE and requester-pays come from `POIESIS_S3_*`."""
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://seaweedfs:9000")
    monkeypatch.setenv(S3_VIRTUAL_HOSTED_STYLE_ENV, "true")
    monkeypatch.setenv(S3_SERVER_SIDE_ENCRYPTION_ENV, "aws:kms")
    monkeypatch.setenv(S3_SSE_KMS_KEY_ID_ENV, "arn:aws:kms:eu-west-1:1:key/k")
    monkeypatch.setenv(S3_REQUESTER_PAYS_ENV, "true")
    store = make_store(ObjectUrl("s3", "bucket", "k"))
    assert isinstance(store, S3Store)
    assert store.config == {
        "bucket": "bucket",
        "virtual_hosted_style_request": "true",
        "server_side_encryption": "aws:kms",
        "sse_kms_key_id": "arn:aws:kms:eu-west-1:1:key/k",
        "request_payer": "true",
    }
    assert store.client_options is not None
    assert store.client_options.get("allow_http") == "true"


def test_s3_defaults_are_path_style_over_https(monkeypatch) -> None:
    """Nothing set: no options, and plain HTTP is not allowed."""
    for name in (
        "AWS_ENDPOINT_URL",
        S3_VIRTUAL_HOSTED_STYLE_ENV,
        S3_SERVER_SIDE_ENCRYPTION_ENV,
        S3_SSE_KMS_KEY_ID_ENV,
        S3_REQUESTER_PAYS_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    store = make_store(ObjectUrl("s3", "bucket", "k"))
    assert isinstance(store, S3Store)
    assert store.config == {"bucket": "bucket"}
    assert store.client_options is not None
    assert "allow_http" not in store.client_options


def test_gcs_and_azure_stores(monkeypatch) -> None:
    """`gs://` and `az://` get their providers' stores."""
    for name in ("GOOGLE_SERVICE_ACCOUNT_KEY", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "account")
    assert isinstance(make_store(ObjectUrl("gs", "bucket", "k")), GCSStore)
    azure = make_store(ObjectUrl("az", "container", "k"))
    assert isinstance(azure, AzureStore)
    assert azure.config == {"container_name": "container"}


def test_gcs_and_azure_endpoints_allow_http_only_when_they_are_http(
    monkeypatch,
) -> None:
    """An ``http://`` endpoint (an emulator) needs plain HTTP; https doesn't."""
    for name in ("GOOGLE_SERVICE_ACCOUNT_KEY", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "account")
    for scheme, name in (("gs", "GOOGLE_BASE_URL"), ("az", "AZURE_STORAGE_ENDPOINT")):
        monkeypatch.setenv(name, "http://emulator:10000")
        store = make_store(ObjectUrl(scheme, "bucket", "k"))
        assert store.client_options is not None
        assert store.client_options.get("allow_http") == "true", scheme
        monkeypatch.setenv(name, "https://private.example")
        store = make_store(ObjectUrl(scheme, "bucket", "k"))
        assert store.client_options is not None
        assert "allow_http" not in store.client_options, scheme

