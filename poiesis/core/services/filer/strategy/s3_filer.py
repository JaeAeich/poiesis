"""S3 filer strategy module."""

import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.config import Config

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.strategy.filer_strategy import (
    InputFilerStrategy,
    OutputFilerStrategy,
)

logger = logging.getLogger(__name__)


class S3FilerStrategy(InputFilerStrategy, OutputFilerStrategy):
    """S3 filer strategy — handles both inputs and outputs."""

    def __init__(self, payload: TesInput | TesOutput):
        """Initialize S3 filer strategy.

        Args:
            payload: The payload to instantiate the strategy
                implementation.
        """
        super().__init__(payload)
        self.input = self.payload if isinstance(self.payload, TesInput) else None
        self.output = self.payload if isinstance(self.payload, TesOutput) else None
        self.key = ""
        self.bucket = ""

        if self.payload.url is None:
            raise ValueError("S3 payload URL is required")
        self._set_bucket_key(self.payload.url)

        if not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")):
            raise ValueError(
                "AWS credentials are not set, ask your administrator to set them."
            )

        # boto3 reads AWS_ENDPOINT_URL, AWS_REGION, and credentials from the
        # environment natively — no manual plumbing here.
        self.client: Any = boto3.client("s3", config=Config(signature_version="s3v4"))

    def _sanitize_s3_key(self, key: str) -> str:
        """Derives a base S3 prefix from a key that may contain glob patterns."""
        glob_pattern = re.compile(r"[\*\?\[\{]")
        match = glob_pattern.search(key)

        if not match:
            return key

        pattern_start_index = match.start()
        last_slash_index = key.rfind("/", 0, pattern_start_index)

        if last_slash_index == -1:
            return ""

        return key[: last_slash_index + 1]

    def _set_bucket_key(self, url: str):
        """Parse `s3://bucket/key...` into bucket + sanitized key prefix."""
        parsed = urlparse(url)
        if parsed.scheme != "s3":
            raise ValueError(f"URL must start with s3://, got: {url}")
        if not parsed.netloc:
            raise ValueError("Bucket name could not be determined from S3 URL.")
        self.bucket = parsed.netloc
        raw_key = parsed.path.lstrip("/")
        self.key = self._sanitize_s3_key(raw_key)

    async def download_input_file(self, container_path: str) -> None:
        """Download file from S3 or MinIO onto the PVC at `container_path`."""
        assert self.input is not None
        try:
            self.client.download_file(self.bucket, self.key, container_path)
            logger.info("Downloaded file from %s to %s", self.input.url, container_path)
        except Exception:
            logger.exception("S3 download failed")
            raise

    async def download_input_directory(self, container_path: str) -> None:
        """Recursively download every object under `self.key` to the PVC."""
        assert self.input is not None
        prefix = (
            self.key if self.key.endswith("/") else (f"{self.key}/" if self.key else "")
        )
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    s3_key = obj["Key"]
                    if not s3_key.startswith(prefix):
                        continue
                    relative_path = s3_key[len(prefix) :] if prefix else s3_key
                    local_path = os.path.join(container_path, relative_path)
                    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
                    logger.info(
                        "Downloading s3://%s/%s to %s",
                        self.bucket,
                        s3_key,
                        local_path,
                    )
                    self.client.download_file(self.bucket, s3_key, local_path)
            logger.info(
                "Downloaded directory from %s to %s",
                self.input.url,
                container_path,
            )
        except Exception:
            logger.exception("S3 directory download failed")
            raise

    async def upload_output_file(self, container_path: str) -> None:
        """Upload a single output file from the PVC to S3 / MinIO."""
        assert self.output is not None
        if not os.path.exists(container_path):
            raise FileNotFoundError(f"Output file not found: {container_path}")
        try:
            self.client.upload_file(container_path, self.bucket, self.key)
            logger.info("Uploaded %s to %s", container_path, self.output.url)
        except Exception:
            logger.exception("S3 upload failed")
            raise

    async def upload_output_directory(self, container_path: str) -> None:
        """Recursively upload `container_path` to S3 / MinIO under `self.key`."""
        assert self.output is not None
        if not os.path.exists(container_path):
            raise FileNotFoundError(f"Output directory not found: {container_path}")
        prefix = self.key if self.key.endswith("/") else f"{self.key}/"
        try:
            for root, _, files in os.walk(container_path):
                for file in files:
                    local_file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_file_path, container_path)
                    s3_key = prefix + relative_path.replace("\\", "/")
                    logger.info(
                        "Uploading %s to s3://%s/%s",
                        local_file_path,
                        self.bucket,
                        s3_key,
                    )
                    self.client.upload_file(local_file_path, self.bucket, s3_key)
            logger.info(
                "Uploaded directory from %s to %s",
                container_path,
                self.output.url,
            )
        except Exception:
            logger.exception("S3 directory upload failed")
            raise

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]):
        """Upload files and directories using wildcard pattern.

        Args:
            glob_files: List of tuples containing (file_path, relative_path,
                is_directory)
        """
        assert self.output is not None
        logger.info(
            "Uploading %d glob-matched items to s3://%s/%s",
            len(glob_files),
            self.bucket,
            self.key,
        )
        for file_path, relative_path, is_directory in glob_files:
            prefix = self.key if self.key.endswith("/") else f"{self.key}/"
            _s3_key = prefix + relative_path
            if is_directory:
                logger.warning(
                    f"Glob pattern matched directory '{file_path}' - uploading as"
                    f"directory (this may not be the intended behavior)"
                )
                # Upload directory contents recursively
                for root, _, files in os.walk(file_path):
                    for file in files:
                        local_file_path = os.path.join(root, file)
                        # Get relative path from the matched directory
                        relative_file_path = os.path.relpath(local_file_path, file_path)
                        # Construct the destination key in S3
                        file_s3_key = f"{_s3_key}/" + relative_file_path.replace(
                            "\\", "/"
                        )

                        logger.debug(
                            "Uploading %s to s3://%s/%s",
                            local_file_path,
                            self.bucket,
                            file_s3_key,
                        )
                        self.client.upload_file(
                            local_file_path, self.bucket, file_s3_key
                        )
            else:
                logger.debug(
                    f"Uploading {file_path} to s3://{self.bucket}/{_s3_key}",
                )
                self.client.upload_file(file_path, self.bucket, _s3_key)
