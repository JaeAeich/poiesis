"""HTTP filer strategy module."""

import requests

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy


class HttpFilerStrategy(FilerStrategy):
    """Filer strategy for HTTP and HTTPS."""

    def __init__(self, payload: TesInput | TesOutput):
        """Initialize the HTTP filer strategy.

        Args:
            payload: The payload to instantiate the strategy
                implementation.
        """
        super().__init__(payload)
        self.input = self.payload

    def get_secrets(self):
        """Get secrets if needed for the protocol."""
        pass

    def check_permissions(self):
        """Check if the user has the necessary permissions."""
        pass

    async def download_input(self, container_path: str):
        """Download the input file from the HTTP or HTTPS URI.

        Args:
            container_path: The path to download the file to.
        """
        if self.input.url is None:
            raise ValueError("URL is required")

        response = requests.get(self.input.url, stream=True, timeout=30)

        with open(container_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    async def upload_output(self, container_path: str):
        """Upload the output file to the HTTP or HTTPS URI.

        Args:
            output: The output file to upload.
            container_path: The path to upload the file from.
        """
        raise NotImplementedError("Uploading to HTTP or HTTPS is not supported")
