"""Local filer strategy module."""

from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy


class LocalFilerStrategy(FilerStrategy):
    """Local filer strategy."""

    def get_secrets(self):
        """No need for secrets for local files."""
        pass

    def check_permissions(self):
        """Authentication is enough for local files.

        No need for authorization checks.
        """
        pass

    def download_input(self):
        """Download file from storage and mount to PVC."""
        pass

    def upload_output(self):
        """Upload file to storage created by executors, mounted to PVC."""
        pass
