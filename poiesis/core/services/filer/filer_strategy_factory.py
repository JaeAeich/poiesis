"""Filer strategy factory module.

Get the correct strategy based on the URI scheme.
"""

import logging
from typing import Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel

from poiesis.api.tes.models import TesInput, TesOutput
from poiesis.core.services.filer.strategy.content_filer import ContentFilerStrategy
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy
from poiesis.core.services.filer.strategy.http_filer import HttpFilerStrategy
from poiesis.core.services.filer.strategy.local_filer import (
    LocalFilerStrategy,
)
from poiesis.core.services.filer.strategy.s3_filer import S3FilerStrategy

logger = logging.getLogger(__name__)


class StrategyInfoDict(BaseModel):
    """Typed dictionary for strategy mapping."""

    name: str
    strategy: type[FilerStrategy]
    input: bool
    output: bool


STRATEGY_MAP: dict[str, StrategyInfoDict] = {
    "": StrategyInfoDict(
        name="content",
        strategy=LocalFilerStrategy,  # Empty scheme for local paths
        input=True,
        output=False,
    ),
    "file": StrategyInfoDict(
        name="file",
        strategy=LocalFilerStrategy,  # file:// URLs
        input=True,
        output=True,
    ),
    "s3": StrategyInfoDict(
        name="s3",
        strategy=S3FilerStrategy,  # s3:// URLs
        input=True,
        output=True,
    ),
    "http": StrategyInfoDict(
        name="http",
        strategy=HttpFilerStrategy,  # http:// URLs
        input=True,
        output=False,
    ),
    "https": StrategyInfoDict(
        name="https",
        strategy=HttpFilerStrategy,  # https:// URLs
        input=True,
        output=False,
    ),
}


class FilerStrategyFactory:
    """Factory for creating filer strategies based on URI scheme.

    This factory class provides a method to create appropriate filer strategy
    instances based on the URI scheme provided.

    Attributes:
        STRATEGY_MAP: A mapping of URI schemes to their corresponding
            filer strategy classes.
    """

    @classmethod
    def create_strategy(
        cls, uri: Optional[str], payload: Union[TesInput, TesOutput]
    ) -> FilerStrategy:
        """Create appropriate strategy based on URI scheme.

        Args:
            uri (str): The URI string to determine the strategy.
            payload (TesInput or TesOutput): The payload to instantiate the strategy
                implementation.

        Returns:
            FilerStrategy: An instance of the appropriate filer strategy.

        Example:
            >>> strategy = FilerStrategyFactory.create_strategy("s3://mybucket/myfile")
            >>> isinstance(strategy, S3FilerStrategy)
            True

        Note:
            If the URI scheme is not recognized, the LocalFilerStrategy will be used
            as the default strategy.
        """
        scheme = urlparse(uri).scheme.lower() if uri else None

        if scheme is None:
            return ContentFilerStrategy(payload)
        strategy_info = STRATEGY_MAP.get(scheme)
        if strategy_info is None:
            raise ValueError(f"Unsupported scheme: {scheme}")
        return strategy_info.strategy(payload)
