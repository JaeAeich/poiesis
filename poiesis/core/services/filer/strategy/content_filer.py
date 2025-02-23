"""Content filer strategy module."""

from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy


class ContentFilerStrategy(FilerStrategy):
    """Content filer, if the content is given in the request."""

    def get_secrets(self):
        """No need for secrets for content."""
        pass

    def check_permissions(self):
        """Authentication is enough for content.

        No need for authorization checks.
        """
        pass

    def download_input(self):
        """Get the content from request and mount to PVC."""
        pass

    def upload_output(self):
        """Mount the content to PVC."""
        pass
