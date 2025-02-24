"""Content filer strategy module."""

import os

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy


class ContentFilerStrategy(FilerStrategy):
    """Content filer, if the content is given in the request."""

    def get_secrets(self):
        """No need for secrets for content."""
        pass

    def check_permissions(self):
        """Authentication is enough for content.

        Just check if the directory exists. No need for authorization checks.
        """
        os.makedirs(os.path.dirname(input.path), exist_ok=True)

    def download_input(self, input: TesInput) -> None:
        """Get the content from request and mount to PVC."""
        content = input.content.encode("utf-8")
        with open(input.path, "wb") as f:
            f.write(content)

    def upload_output(self, output: TesOutput) -> None:
        """Mount the content to PVC."""
        raise NotImplementedError(
            "Content filer does not support uploads according to TES spec."
        )
