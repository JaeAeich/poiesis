"""S3 filer strategy module."""

from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy


class S3FilerStrategy(FilerStrategy):
    """S3 filer strategy."""

    def get_secrets(self):
        """Get secrets for S3."""
        pass

    def check_permissions(self):
        """Check if the user has the necessary permissions for S3 bucket."""
        pass

    def download_input(self):
        """Download file from S3 or Minio and mount to PVC."""
        pass

    def upload_output(self):
        """Upload file to S3 or Minio created by executors, mounted to PVC."""
        pass
