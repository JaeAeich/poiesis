"""S3 filer strategy module."""

import logging
import os
from typing import Any

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

        if self.s3_host is None:
            raise ValueError(
                "Host URL is required, either as part of the URL or as an "
                "environment variable."
            )
        try:
            self.client: Any = boto3.client(
                "s3",
                endpoint_url=self.s3_host,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                config=Config(signature_version="s3v4"),
            )
        except Exception as e:
            logger.error("Error creating S3 client: %s", e)
            raise

    def get_secrets(self) -> None:
        """Get secrets for S3.

        The filer job should have the following environment variables set:
            - AWS_ACCESS_KEY_ID
            - AWS_SECRET_ACCESS_KEY
        """
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

    def check_permissions(self) -> None:
        """Check if the user has the necessary permissions for S3 bucket.

        If the bucket does not exist, it will be created automatically.
        """
        try:
            if self.payload.url is None:
                raise ValueError("URI is required")
            logger.info("Checking permissions for bucket: %s", self.bucket)
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except self.client.exceptions.ClientError as e:
                if e.response["Error"]["Code"] != "404":
                    raise

                logger.warning("Bucket %s does not exist. Creating it...", self.bucket)
                self.client.create_bucket(Bucket=self.bucket)
                logger.info("Created bucket: %s", self.bucket)
            self.client.list_objects_v2(Bucket=self.bucket)
        except Exception as e:
            logger.error(
                f"Error checking permissions at {self.s3_host} for "
                f"bucket: {self.bucket}"
            )
            logger.error("Listing error: %s", e)
            raise

    def _set_host_bucket_key(self, url: str):
        """Get the bucket name and key from the URL."""
        stripped_url = url.split("s3://")[1].split("/")
        if len(stripped_url) >= 3:  # noqa: PLR2004
            self.s3_host = stripped_url[0]
            self.bucket = stripped_url[1]
            self.key = "/".join(stripped_url[2:])
        elif len(stripped_url) == 2:  # noqa: PLR2004
            self.s3_host = os.getenv("S3_URL")
            self.bucket = stripped_url[0]
            self.key = stripped_url[1]
        else:
            raise ValueError("Invalid S3 URL, could not extract bucket and key.")

    async def download_input(self, container_path: str) -> None:
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

    async def upload_output(self, container_path: str) -> None:
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
