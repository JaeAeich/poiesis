"""HTTP filer strategy — input-only.

Per the TES spec, HTTP(S) URLs are only valid as inputs. Output to HTTP
is not supported by the strategy interface; the factory rejects it.
"""

import requests

from poiesis.api.tes.models import TesInput
from poiesis.core.services.filer.strategy.filer_strategy import InputFilerStrategy


class HttpFilerStrategy(InputFilerStrategy):
    """Filer strategy for HTTP and HTTPS inputs."""

    def __init__(self, payload: TesInput):
        """Initialise with the TES input."""
        super().__init__(payload)
        self.input = payload

    async def download_input_file(self, container_path: str) -> None:
        """Stream the input file from the HTTP(S) URL to `container_path`."""
        if self.input.url is None:
            raise ValueError("URL is required")

        response = requests.get(self.input.url, stream=True, timeout=30)

        with open(container_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    async def download_input_directory(self, container_path: str) -> None:
        """HTTP directory listing is not standardised; refuse."""
        raise NotImplementedError(
            "Downloading directories over HTTP/HTTPS is not supported"
        )
