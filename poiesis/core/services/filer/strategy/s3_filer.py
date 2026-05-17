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
        self.s3_host: str | None = None
        self.key = ""
        self.bucket = ""

        assert self.payload.url is not None, "URL is required"
        self._set_host_bucket_key(self.payload.url)
        assert self.key is not None, "S3 key must be set after parsing URL"
        assert self.bucket is not None, "S3 bucket must be set after parsing URL"
        assert self.bucket != "", "S3 bucket must not be empty"

        if not all(
            [
                os.getenv("AWS_ACCESS_KEY_ID"),
                os.getenv("AWS_SECRET_ACCESS_KEY"),
            ]
        ):
            logger.debug("AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are not set")
            raise ValueError(
                "AWS credentials are not set, ask your administrator to set them."
            )

        try:
            client_args: dict[str, Any] = {
                "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
                "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
                "config": Config(signature_version="s3v4"),
            }

            if os.getenv("AWS_REGION"):
                client_args["region_name"] = os.getenv("AWS_REGION")

            if self.s3_host:
                endpoint_url = self.s3_host
                if not endpoint_url.startswith(("http://", "https://")):
                    logger.warning(
                        "S3 host '%s' has no scheme, defaulting to 'http://'",
                        endpoint_url,
                    )
                    endpoint_url = f"http://{endpoint_url}"
                client_args["endpoint_url"] = endpoint_url

            self.client: Any = boto3.client("s3", **client_args)
            logger.info(
                f"S3 Endpoint: {client_args.get('endpoint_url', 'Default AWS')}, "
                f"S3 Region: {client_args.get('region_name', 'Default')}",
            )

        except Exception as e:
            logger.error(f"Error creating S3 client: {e}")
            raise

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

    def _set_host_bucket_key(self, url: str):
        """Get the bucket name and key from the URL."""
        parsed = urlparse(url)

        if parsed.scheme != "s3":
            raise ValueError(f"URL must start with s3://, got: {url}")

        path_parts = parsed.path.lstrip("/").split("/")

        is_host_in_netloc = parsed.netloc and (
            "." in parsed.netloc or ":" in parsed.netloc
        )

        if is_host_in_netloc:
            self.s3_host = parsed.netloc
            if path_parts and path_parts[0]:
                self.bucket = path_parts[0]
                raw_key = "/".join(path_parts[1:])
            else:
                raise ValueError("Bucket not found in URL path after host.")
        else:
            # The host might be set via an environment variable for other S3-compatibles
            self.s3_host = os.getenv("S3_URL")
            self.bucket = parsed.netloc
            raw_key = parsed.path.lstrip("/")

        if not self.bucket:
            raise ValueError("Bucket name could not be determined from S3 URL.")

        self.key = self._sanitize_s3_key(raw_key)
        logger.debug(f"Raw S3 key '{raw_key}' sanitized to prefix '{self.key}'")

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
