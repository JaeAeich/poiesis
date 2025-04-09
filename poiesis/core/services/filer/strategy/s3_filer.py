"""S3 filer strategy module."""

import logging
import os
from typing import Optional

import boto3
from botocore.config import Config

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

logger = logging.getLogger(__name__)

core_constants = get_poiesis_core_constants()


class S3FilerStrategy(FilerStrategy):
    """S3 filer strategy."""

    def __init__(self):
        """Initialize S3 filer strategy."""
        try:
            self.client = boto3.client(
                "s3",
                endpoint_url=os.getenv("S3_URL"),
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                config=Config(signature_version="s3v4"),
            )
        except Exception as e:
            logger.error("Error creating S3 client: %s", e)
            raise

    def get_secrets(self, uri: Optional[str], path: str) -> None:
        """Get secrets for S3.

        The filer job should have the following environment variables set:
            - AWS_ACCESS_KEY_ID
            - AWS_SECRET_ACCESS_KEY
            - S3_URL
        """
        if not all(
            [
                os.getenv("AWS_ACCESS_KEY_ID"),
                os.getenv("AWS_SECRET_ACCESS_KEY"),
                os.getenv("S3_URL"),
            ]
        ):
            logger.error("S3_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY must be set")
            raise ValueError(
                "S3_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY must be set"
            )

    def check_permissions(self, uri: Optional[str], path: str):
        """Check if the user has the necessary permissions for S3 bucket."""
        try:
            if uri is None:
                raise ValueError("URI is required")
            bucket, _ = self._get_bucket_key(uri)
            logger.info("Checking permissions for bucket: %s", bucket)
            self.client.list_objects_v2(Bucket=bucket)
        except Exception as e:
            logger.error("Listing error: %s", e)
            raise

    def _get_bucket_key(self, url: str) -> tuple[str, str]:
        """Get the bucket name and key from the URL."""
        bucket_name = url.split("/")[2]
        key = "/".join(url.split("/")[3:])
        return bucket_name, key

    async def download_input(self, tes_input: TesInput, container_path: str) -> None:
        """Download file from S3 or Minio and mount to PVC.

        Download file from S3 or Minio to the path location which is mounted to PVC.

        Args:
            tes_input: The input object from the TES task request.
            container_path: The path inside the container where the file needs to be
                downloaded to.
        """
        assert tes_input.url is not None

        bucket_name, key = self._get_bucket_key(tes_input.url)

        try:
            self.client.download_file(bucket_name, key, container_path)
            logger.info(
                "Successfully downloaded file from %s to %s",
                tes_input.url,
                container_path,
            )
        except Exception as e:
            logger.error("Error downloading file: %s", e)
            raise

    async def upload_output(self, tes_output: TesOutput, container_path: str) -> None:
        """Upload file to S3 or Minio created by executors, mounted to PVC.

        Upload file to S3 or Minio from the path location to the S3 or Minio bucket.
        If the bucket doesn't exist, it will be created automatically.

        Args:
            tes_output: The output object from the TES task request
            container_path: The path inside the container from where the file needs to
                be uploaded from.
        """
        assert tes_output.url is not None

        bucket_name, key = self._get_bucket_key(tes_output.url)

        try:
            try:
                self.client.head_bucket(Bucket=bucket_name)
            except self.client.exceptions.ClientError as e:
                if e.response["Error"]["Code"] != "404":
                    raise

                logger.info("Bucket %s does not exist. Creating it...", bucket_name)
                self.client.create_bucket(Bucket=bucket_name)
                logger.info("Created bucket: %s", bucket_name)
            if not os.path.exists(container_path):
                logger.error("Output file not found: %s", container_path)
                raise FileNotFoundError(f"Output file not found: {container_path}")

            self.client.upload_file(container_path, bucket_name, key)
            logger.info("Uploaded %s to %s", container_path, tes_output.url)
        except Exception as e:
            logger.error("Error uploading file: %s", e)
            raise
