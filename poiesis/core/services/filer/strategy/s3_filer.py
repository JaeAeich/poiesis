"""S3 filer strategy module."""

import logging
import os
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

        assert self.payload.url is not None, "URL is required"
        self._set_host_bucket_key(self.payload.url)

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

        if self.s3_host is None:
            raise ValueError(
                "Host URL is required, either as part of the URL or as an "
                "environment variable."
            )
        try:
            if not self.s3_host.startswith(("http://", "https://")):
                _endpoint_url = f"http://{self.s3_host}"
            else:
                _endpoint_url = self.s3_host
            self.client: Any = boto3.client(
                "s3",
                endpoint_url=_endpoint_url,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                config=Config(signature_version="s3v4"),
            )
        except Exception as e:
            logger.error("Error creating S3 client: %s", e)
            raise

    def _set_host_bucket_key(self, url: str):
        """Get the bucket name and key from the URL.

        Example:
            - `s3://host:port/bucket_name/`
            - `s3://host/bucket_name/file_path`
            - `s3://bucket_name/dir_name`
            - `s3://host/bucket_name/dir_name/`
            - `s3://bucket_name/`
        """
        parsed = urlparse(url)

        if parsed.scheme != "s3":
            raise ValueError(f"URL must start with s3://, got: {url}")

        path_parts = parsed.path.lstrip("/").split("/")

        if parsed.netloc and parsed.netloc.count(".") > 0 or ":" in parsed.netloc:
            # Case: s3://host[:port]/bucket/key
            self.s3_host = f"http://{parsed.netloc}"  # Add scheme
            if len(path_parts) >= 1:
                self.bucket = path_parts[0]
            else:
                raise ValueError("Bucket not found in URL.")
            self.key = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""
        else:
            # Case: s3://bucket/key
            self.s3_host = os.getenv("S3_URL")
            self.bucket = parsed.netloc
            self.key = "/".join(path_parts) if path_parts else ""

        if not self.bucket:
            raise ValueError("Bucket name could not be determined from S3 URL.")
        if not self.s3_host:
            raise ValueError("S3 host is not defined and could not be inferred.")

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
                "Successfully downloaded file from %s to %s",
                self.input.url,
                container_path,
            )
        except Exception as e:
            logger.error("Error downloading file: %s", e)
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
        assert self.input is not None
        assert self.input.url is not None

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
                        "Downloading s3://%s/%s to %s", self.bucket, s3_key, local_path
                    )
                    self.client.download_file(self.bucket, s3_key, local_path)

            logger.info(
                "Successfully downloaded directory from %s to %s",
                self.input.url,
                container_path,
            )

        except Exception as e:
            logger.error("Error downloading directory: %s", e)
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
                logger.error("Output file not found: %s", container_path)
                raise FileNotFoundError(f"Output file not found: {container_path}")

            self.client.upload_file(container_path, self.bucket, self.key)
            logger.info("Uploaded %s to %s", container_path, self.output.url)
        except Exception as e:
            logger.error("Error uploading file: %s", e)
            raise

    async def upload_output_directory(self, container_path: str) -> None:
        """Upload directory to S3 or Minio created by executors, mounted to PVC.

        Args:
            container_path: The path inside the container from where the directory
                needs to be uploaded.
        """
        assert self.output is not None

        try:
            if not os.path.exists(container_path):
                logger.error("Output directory not found: %s", container_path)
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
                        "Uploading %s to s3://%s/%s",
                        local_file_path,
                        self.bucket,
                        s3_key,
                    )
                    self.client.upload_file(local_file_path, self.bucket, s3_key)

            logger.info(
                "Successfully uploaded directory from %s to %s",
                container_path,
                self.output.url,
            )

        except Exception as e:
            logger.error("Error uploading directory: %s", e)
            raise

    async def upload_glob(self, glob_files: list[tuple[str, str]]):
        """Upload file using wildcard pattern.

        Args:
            glob_files: List of tuple of file path of and its prefix removed
                path that needs to be appended to url.
        """
        assert self.output is not None
        for file_path, relative_path in glob_files:
            prefix = self.key if self.key.endswith("/") else f"{self.key}/"
            _s3_key = prefix + relative_path

            logger.info(
                "Uploading %s to s3://%s/%s",
                file_path,
                self.bucket,
                str(_s3_key),
            )
            self.client.upload_file(file_path, self.bucket, _s3_key)
