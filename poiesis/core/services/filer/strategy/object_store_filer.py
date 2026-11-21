"""Object-store filer strategy: S3, Google Cloud Storage and Azure Blob.

One strategy for every object store, on obstore (Python bindings to the
Rust ``object_store`` crate). A URL names a bucket (a container, for Azure)
and a key: ``s3://bucket/key``, ``gs://bucket/key``, ``az://container/blob``.
The key is taken as written: ``?``, ``#`` and glob characters are part of
it, not a query, a fragment or a pattern.

Credentials come from each provider's default chain, which obstore reads
from the environment: static keys, a web-identity token file (IRSA, Azure
workload identity), instance metadata. The API sets that environment on
TIF and TOF only; see the "Storage" docs page.

Transfers stream: a download is written to the volume as it arrives, an
upload is sent in parts read from the file. A DIRECTORY or glob moves up
to `MAX_PARALLEL_TRANSFERS` files at once. obstore retries 5xx responses,
dropped connections and timeouts with exponential backoff (`_RETRY`).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import obstore
from obstore.exceptions import BaseError
from obstore.store import AzureStore, GCSStore, S3Store

from poiesis.core.constants import (
    S3_REQUESTER_PAYS_ENV,
    S3_SERVER_SIDE_ENCRYPTION_ENV,
    S3_SSE_KMS_KEY_ID_ENV,
    S3_VIRTUAL_HOSTED_STYLE_ENV,
)
from poiesis.core.services.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    OutputFilerStrategy,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from obstore.store import ClientConfig, ObjectStore, RetryConfig

    from poiesis.api.tes.models import TesInput, TesOutput

logger = logging.getLogger(__name__)

#: URL schemes this strategy serves, by provider.
SCHEMES: tuple[str, ...] = ("s3", "gs", "az")

#: Files of one DIRECTORY or glob transferred at once.
MAX_PARALLEL_TRANSFERS = 4
#: Parts of one file uploaded at once.
_PART_CONCURRENCY = 4
#: Smallest upload part, and the size of each chunk written on download.
_CHUNK_BYTES = 8 * 1024 * 1024
#: S3 allows 10 000 parts per upload; parts grow to stay below this.
_MAX_PARTS = 9000

#: obstore's defaults, written out: up to 10 retries with exponential
#: backoff and jitter, none started more than 3 minutes after the first try.
_RETRY: RetryConfig = {"max_retries": 10, "retry_timeout": timedelta(minutes=3)}
#: A download streams for as long as the file takes, so the overall request
#: timeout (30 s by default) is lifted; a read that stalls for a minute is
#: retried instead.
_CLIENT: ClientConfig = {
    "timeout": timedelta(hours=24),
    "read_timeout": timedelta(minutes=1),
}

_GLOB_CHARS = "*?[{"


class ObjectStoreError(OSError):
    """A request to an object store failed."""


@dataclass(frozen=True)
class ObjectUrl:
    """An object-store URL split into its parts."""

    scheme: str
    bucket: str
    key: str

    def url(self, key: str) -> str:
        """The URL of `key` in the same bucket."""
        return f"{self.scheme}://{self.bucket}/{key}"


def parse_object_url(url: str) -> ObjectUrl:
    """Split `url` into scheme, bucket and key, keeping the key as written.

    Not `urlparse`: it would cut the key at ``?`` or ``#``.
    """
    scheme, sep, rest = url.partition("://")
    scheme = scheme.lower()
    if not sep or scheme not in SCHEMES:
        raise ValueError(f"not an object-store URL: {url!r}")
    bucket, _, key = rest.partition("/")
    if not bucket:
        raise ValueError(f"{url!r} names no bucket")
    return ObjectUrl(scheme=scheme, bucket=bucket, key=key)


def make_store(location: ObjectUrl) -> ObjectStore:
    """The obstore store for `location`'s bucket, configured from the env."""
    if location.scheme == "s3":
        endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
        client: ClientConfig = {**_CLIENT}
        if endpoint.startswith("http://"):
            client["allow_http"] = True
        return S3Store(
            location.bucket,
            config=s3_options(),
            client_options=client,
            retry_config=_RETRY,
        )
    if location.scheme == "gs":
        return GCSStore(location.bucket, client_options=_CLIENT, retry_config=_RETRY)
    return AzureStore(
        container_name=location.bucket,
        client_options=_CLIENT,
        retry_config=_RETRY,
    )


def s3_options() -> dict[str, Any]:
    """S3 options the API passes as ``POIESIS_S3_*``; obstore reads the rest.

    Endpoint, region and credentials come from the standard ``AWS_*``
    variables. Path-style addressing is the default.
    """
    options: dict[str, Any] = {}
    if _flag(S3_VIRTUAL_HOSTED_STYLE_ENV):
        options["virtual_hosted_style_request"] = True
    if sse := os.environ.get(S3_SERVER_SIDE_ENCRYPTION_ENV):
        options["server_side_encryption"] = sse
    if kms_key := os.environ.get(S3_SSE_KMS_KEY_ID_ENV):
        options["sse_kms_key_id"] = kms_key
    if _flag(S3_REQUESTER_PAYS_ENV):
        options["request_payer"] = True
    return options


def _flag(name: str) -> bool:
    return os.environ.get(name, "").lower() == "true"


def child_key(prefix: str, relative: str) -> str:
    """`relative` below the key `prefix`; ``out`` and ``out/`` give ``out/x``."""
    base = prefix.rstrip("/")
    return f"{base}/{relative}" if base else relative


def glob_base(key: str) -> str:
    """The key up to the last ``/`` before its first glob character.

    For an output URL written as a glob (``s3://b/out/*.vcf``), matches
    are uploaded below ``out/``. Used for glob outputs only: input keys
    and other output keys are taken as written.
    """
    starts = [i for i in (key.find(c) for c in _GLOB_CHARS) if i != -1]
    if not starts:
        return key
    slash = key.rfind("/", 0, min(starts))
    return "" if slash == -1 else key[: slash + 1]


def plan_directory_download(
    prefix: str, keys: Iterable[str], dest: str
) -> list[tuple[str, str]]:
    """``(key, local path)`` for each object under `prefix`, staged below `dest`.

    Folder markers are skipped: a key ending in ``/``, or one that names a
    directory of other keys (obstore lists ``dir/`` as ``dir``). A key whose
    path would land outside `dest` (``..``, a leading ``/``) is refused.
    """
    base = prefix.rstrip("/")
    start = f"{base}/" if base else ""
    relative: dict[str, str] = {}
    for key in keys:
        if not key.startswith(start):
            continue
        rel = key[len(start) :]
        if not rel or rel.endswith("/"):
            logger.debug("Skipping folder marker %s", key)
            continue
        relative[key] = rel
    directories = {parent for rel in relative.values() for parent in _parents(rel)}
    root = os.path.normpath(dest)
    plan: list[tuple[str, str]] = []
    for key, rel in sorted(relative.items()):
        if rel in directories:
            logger.info("Skipping %s: other objects are below it", key)
            continue
        local = os.path.normpath(os.path.join(root, rel))
        if not local.startswith(root + os.sep):
            raise ValueError(f"object key {key!r} leads outside the input directory")
        plan.append((key, local))
    return plan


def _parents(rel: str) -> list[str]:
    """Each proper parent of the relative path `rel` (``a/b/c`` → a, a/b)."""
    parts = rel.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def walk_files(directory: str) -> list[tuple[str, str]]:
    """``(path, path relative to directory)`` for each file under `directory`.

    Symlinked directories are not followed, as with `os.walk`.
    """
    files: list[tuple[str, str]] = []
    for root, dirs, names in os.walk(directory):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(root, name)
            files.append((path, os.path.relpath(path, directory).replace("\\", "/")))
    return files


async def run_bounded(jobs: list[Callable[[], Awaitable[None]]]) -> None:
    """Run `jobs`, at most `MAX_PARALLEL_TRANSFERS` at once.

    The first failure cancels the others and is raised as it is (not in
    an ExceptionGroup), so the filer reports it as the cause.
    """
    gate = asyncio.Semaphore(MAX_PARALLEL_TRANSFERS)

    async def bounded(job: Callable[[], Awaitable[None]]) -> None:
        async with gate:
            await job()

    tasks = [asyncio.ensure_future(bounded(job)) for job in jobs]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _brief(error: BaseException) -> str:
    """The message of an obstore error, without its debug dump."""
    return str(error).split("\n\nDebug source:", 1)[0].strip()


class ObjectStoreFilerStrategy(InputFilerStrategy, OutputFilerStrategy):
    """Inputs and outputs on S3, Google Cloud Storage or Azure Blob."""

    def __init__(self, payload: TesInput | TesOutput, store: ObjectStore | None = None):
        """Initialise for `payload`; `store` defaults to `make_store`."""
        super().__init__(payload)
        if payload.url is None:
            raise ValueError("object-store payload URL is required")
        self.location = parse_object_url(payload.url)
        self.store = store if store is not None else make_store(self.location)

    async def _get(self, key: str, path: str) -> None:
        """Stream the object `key` to the file `path`."""
        url = self.location.url(key)
        logger.info("Downloading %s to %s", url, path)
        try:
            result = await obstore.get_async(self.store, key)
            with open(path, "wb") as f:
                async for chunk in result.stream(min_chunk_size=_CHUNK_BYTES):
                    f.write(chunk)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"GET {url}: no such object") from e
        except BaseError as e:
            raise ObjectStoreError(f"GET {url}: {_brief(e)}") from e

    async def _put(self, path: str, key: str) -> None:
        """Upload the file `path` to `key`, in parts when it is large."""
        url = self.location.url(key)
        logger.info("Uploading %s to %s", path, url)
        size = os.path.getsize(path)
        part = max(_CHUNK_BYTES, -(-size // _MAX_PARTS))
        try:
            await obstore.put_async(
                self.store,
                key,
                Path(path),
                chunk_size=part,
                max_concurrency=_PART_CONCURRENCY,
            )
        except (BaseError, FileNotFoundError) as e:
            raise ObjectStoreError(f"PUT {url}: {_brief(e)}") from e

    async def _list(self, prefix: str) -> list[str]:
        """Keys of the objects below `prefix` (whole path segments)."""
        base = prefix.rstrip("/")
        keys: list[str] = []
        try:
            async for chunk in obstore.list(self.store, prefix=base or None):
                keys.extend(meta["path"] for meta in chunk)
        except BaseError as e:
            raise ObjectStoreError(
                f"LIST {self.location.url(base)}: {_brief(e)}"
            ) from e
        return keys

    async def _put_all(self, files: list[tuple[str, str]]) -> None:
        """Upload each ``(path, key)``, then record them in that order."""
        await run_bounded(
            [lambda p=path, k=key: self._put(p, k) for path, key in files]
        )
        for path, key in files:
            self._record_upload(path, self.location.url(key), redact=False)

    async def download_input_file(self, container_path: str) -> None:
        """Download the object named by the input URL to `container_path`."""
        if not self.location.key or self.location.key.endswith("/"):
            raise ValueError(
                f"FILE input {self.payload.url} names a prefix, not an object"
            )
        await self._get(self.location.key, container_path)

    async def download_input_directory(self, container_path: str) -> None:
        """Download every object below the input URL's key."""
        prefix = self.location.key
        keys = await self._list(prefix)
        plan = plan_directory_download(prefix, keys, container_path)
        if not plan:
            raise FileNotFoundError(
                f"DIRECTORY input {self.payload.url} matches no object"
            )
        os.makedirs(container_path, exist_ok=True)
        for _key, local in plan:
            os.makedirs(os.path.dirname(local), exist_ok=True)
        await run_bounded(
            [lambda k=key, p=local: self._get(k, p) for key, local in plan]
        )
        logger.info("Downloaded %d object(s) from %s", len(plan), self.payload.url)

    async def upload_output_file(self, container_path: str) -> None:
        """Upload `container_path` to the output URL's key."""
        if not os.path.exists(container_path):
            raise FileNotFoundError(f"Output file not found: {container_path}")
        key = self.location.key
        if not key or key.endswith("/"):
            raise ValueError(
                f"FILE output {self.payload.url} names a prefix, not an object"
            )
        await self._put_all([(container_path, key)])

    async def upload_output_directory(self, container_path: str) -> None:
        """Upload each file under `container_path` below the output URL's key."""
        if not os.path.exists(container_path):
            raise FileNotFoundError(f"Output directory not found: {container_path}")
        if not os.path.isdir(container_path):
            raise NotADirectoryError(f"Output is not a directory: {container_path}")
        key = self.location.key
        await self._put_all(
            [(path, child_key(key, rel)) for path, rel in walk_files(container_path)]
        )

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]) -> None:
        """Upload each glob match below the output URL's key plus its path.

        A matched directory is uploaded with everything under it.
        """
        base = glob_base(self.location.key)
        files: list[tuple[str, str]] = []
        for path, relative, is_directory in glob_files:
            key = child_key(base, relative)
            if is_directory:
                logger.warning("Glob matched directory %s; uploading its files", path)
                files.extend(
                    (file, child_key(key, rel)) for file, rel in walk_files(path)
                )
            else:
                files.append((path, key))
        await self._put_all(files)
