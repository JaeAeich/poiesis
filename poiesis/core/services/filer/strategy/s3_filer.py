"""S3 filer strategy module."""

import logging
import os
from typing import Optional

import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

logger = logging.getLogger(__name__)

core_constants = get_poiesis_core_constants()


class S3FilerStrategy(FilerStrategy):
    """S3 filer strategy."""

    def get_secrets(self, uri: Optional[str], path: str) -> None:
        """Get secrets for S3."""
        try:
            s3 = boto3.client("s3")
            s3.list_buckets()
            print("Credentials are valid")
        except NoCredentialsError:
            print("Credentials not available")
            raise
        except PartialCredentialsError:
            print("Incomplete credentials provided")
            raise
        except Exception as e:
            print(f"An error occurred: {e}")
            raise

    def check_permissions(self):
        """Check if the user has the necessary permissions for S3 bucket."""
        pass

    def download_input(self, tes_input: TesInput) -> None:
        """Download file from S3 or Minio and mount to PVC.

        Download file from S3 or Minio to the path location which is mounted to PVC.

        Args:
            tes_input: The input object from the TES task request
        """
        assert tes_input.url is not None
        s3 = boto3.client("s3")
        bucket_name = tes_input.url.split("/")[2]
        key = "/".join(tes_input.url.split("/")[3:])
        download_path = tes_input.path
        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH, tes_input.path.lstrip("/")
        )

        os.makedirs(os.path.dirname(container_path), exist_ok=True)
        try:
            s3.download_file(bucket_name, key, download_path)
            logger.info(f"Downloaded {tes_input.url} to {download_path}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")

    def upload_output(self, tes_output: TesOutput) -> None:
        """Upload file to S3 or Minio created by executors, mounted to PVC.

        Upload file to S3 or Minio from the path location to the S3 or Minio bucket.

        Args:
            tes_output: The output object from the TES task request
        """
        assert tes_output.url is not None
        s3 = boto3.client("s3")
        bucket_name = tes_output.url.split("/")[2]
        key = "/".join(tes_output.url.split("/")[3:])

        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH, tes_output.path.lstrip("/")
        )

        try:
            if not os.path.exists(container_path):
                logger.error(f"Output file not found: {container_path}")
                raise FileNotFoundError(f"Output file not found: {container_path}")

            s3.upload_file(container_path, bucket_name, key)
            logger.info(f"Uploaded {container_path} to {tes_output.url}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
