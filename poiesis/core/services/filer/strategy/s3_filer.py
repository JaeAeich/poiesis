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
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

logger = logging.getLogger(__name__)

core_constants = get_poiesis_core_constants()


class S3FilerStrategy(FilerStrategy):
    """S3 filer strategy."""

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
        assert self.bucket is not None and self.bucket != "", (
            "S3 bucket must be set after parsing URL"
        )

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
                        f"S3 host '{endpoint_url}' does not have a scheme, "
                        "defaulting to 'http://'",
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
        """Download file from S3 or Minio and mount to PVC.

        Download file from S3 or Minio to the path location which is mounted to PVC.

        Args:
            container_path: The path inside the container where the file needs to be
                downloaded to.
        """
        assert self.input is not None
        assert self.input.url is not None

        try:
            self.client.download_file(self.bucket, self.key, container_path)
            logger.info(
                "Successfully downloaded file from "
                f"{self.input.url} to {container_path}"
            )
        except Exception as e:
            logger.error(f"Error downloading file: {e}")
            raise

    async def download_input_directory(self, container_path: str) -> None:
        """Download a directory from S3 or Minio and mount to PVC.

        Download directory from S3 or Minio to the path location which is mounted to
        PVC. I.e if the path is `bucket_name/path_name` then it download all the files
        in `bucket_name/path_name` to container_path.

        Args:
            container_path: The path inside the container where the file needs to be
                downloaded to.
        """
        try:
            prefix = self.key
            if prefix and not prefix.endswith("/"):
                prefix += "/"
            elif not prefix:
                prefix = ""

            paginator = self.client.get_paginator("list_objects_v2")

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    s3_key = obj["Key"]

                    # Skip objects that don't start with prefix
                    if not s3_key.startswith(prefix):
                        continue

                    # Relative path from prefix
                    relative_path = s3_key[len(prefix) :] if prefix else s3_key
                    local_path = os.path.join(container_path, relative_path)

                    # Ensure local directory exists
                    Path(local_path).parent.mkdir(parents=True, exist_ok=True)

                    logger.info(
                        f"Downloading s3://{self.bucket}/{s3_key} to {local_path}"
                    )
                    self.client.download_file(self.bucket, s3_key, local_path)

            assert self.input is not None
            assert self.input.url is not None

            logger.info(
                "Successfully downloaded directory from "
                f"{self.input.url} to {container_path}",
            )

        except Exception as e:
            logger.error(f"Error downloading directory: {e}")
            raise

    async def upload_output_file(self, container_path: str) -> None:
        """Upload file to S3 or Minio created by executors, mounted to PVC.

        Args:
            container_path: The path inside the container from where the file needs to
                be uploaded from.
        """
        assert self.output is not None

        try:
            if not os.path.exists(container_path):
                logger.error(f"Output file not found: {container_path}")
                raise FileNotFoundError(f"Output file not found: {container_path}")

            self.client.upload_file(container_path, self.bucket, self.key)
            logger.info(f"Uploaded {container_path} to {self.output.url}")
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            raise

    async def upload_output_directory(self, container_path: str) -> None:
        """Upload directory to S3 or Minio created by executors, mounted to PVC.

        Args:
            container_path: The path inside the container from where the directory
                needs to be uploaded.
        """
        try:
            if not os.path.exists(container_path):
                logger.error(f"Output directory not found: {container_path}")
                raise FileNotFoundError(f"Output directory not found: {container_path}")

            for root, _, files in os.walk(container_path):
                for file in files:
                    local_file_path = os.path.join(root, file)

                    # Get relative path to maintain directory structure
                    relative_path = os.path.relpath(local_file_path, container_path)

                    # Construct the destination key in S3
                    prefix = self.key if self.key.endswith("/") else f"{self.key}/"
                    s3_key = prefix + relative_path.replace(
                        "\\", "/"
                    )  # Ensure POSIX-style key

                    logger.info(
                        f"Uploading {local_file_path} to s3://{self.bucket}/{s3_key}",
                    )
                    self.client.upload_file(local_file_path, self.bucket, s3_key)

            assert self.output is not None
            assert self.output.url is not None

            logger.info(
                f"Successfully uploaded directory from {container_path} "
                f"to {self.output.url}",
            )

        except Exception as e:
            logger.error(f"Error uploading directory: {e}")
            raise

    async def upload_glob(self, glob_files: list[tuple[str, str, bool]]):
        """Upload files and directories using wildcard pattern.

        Args:
            glob_files: List of tuples containing (file_path, relative_path,
                is_directory)
        """
        assert self.output is not None
        logger.info(
            f"Uploading {len(glob_files)} glob-matched items to s3://{self.bucket}/{self.key}",
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
                            f"Uploading {local_file_path} to s3://{self.bucket}/{file_s3_key}",
                        )
                        self.client.upload_file(
                            local_file_path, self.bucket, file_s3_key
                        )
            else:
                logger.debug(
                    f"Uploading {file_path} to s3://{self.bucket}/{_s3_key}",
                )
                self.client.upload_file(file_path, self.bucket, _s3_key)
