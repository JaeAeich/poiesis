"""Content filer strategy module."""

import logging
import os
from typing import Optional

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.constants import get_poiesis_core_constants
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy

core_constants = get_poiesis_core_constants()
logger = logging.getLogger(__name__)


class ContentFilerStrategy(FilerStrategy):
    """Content filer, if the content is given in the request."""

    def get_secrets(self, uri: Optional[str], path: str):
        """No need for secrets for content."""
        pass

    def check_permissions(self, uri: Optional[str], path: str):
        """Authentication is enough for content.

        Just check if the directory exists. No need for authorization checks.
        """
        pass

    async def download_input(self, _input: TesInput) -> None:
        """Get the content from request and mount to PVC."""
        assert _input.content is not None

        container_path = os.path.join(
            core_constants.K8s.FILER_PVC_PATH, _input.path.lstrip("/")
        )
        os.makedirs(os.path.dirname(container_path), exist_ok=True)

        content = _input.content.encode("utf-8")
        with open(container_path, "wb") as f:
            f.write(content)

        logger.info(f"Created file with content at {container_path}")

    async def upload_output(self, output: TesOutput) -> None:
        """Mount the content to PVC."""
        raise NotImplementedError(
            "Content filer does not support uploads according to TES spec."
        )
