"""Filer strategy factory module.

Get the correct strategy based on the URI scheme.
"""

from typing import Optional
from urllib.parse import urlparse

from poiesis.core.services.filer.strategy.content_filer import ContentFilerStrategy
from poiesis.core.services.filer.strategy.filer_strategy import FilerStrategy
from poiesis.core.services.filer.strategy.local_filer import (
    LocalFilerStrategy,
)
from poiesis.core.services.filer.strategy.s3_filer import S3FilerStrategy


class FilerStrategyFactory:
    """Factory for creating filer strategies based on URI scheme.

    This factory class provides a method to create appropriate filer strategy
    instances based on the URI scheme provided.

    Attributes:
        STRATEGY_MAP: A mapping of URI schemes to their corresponding
            filer strategy classes.
    """

    STRATEGY_MAP: dict[str, type[FilerStrategy]] = {
        "": LocalFilerStrategy,  # Empty scheme for local paths
        "file": LocalFilerStrategy,  # file:// URLs
        "s3": S3FilerStrategy,  # s3:// URLs
    }

    @classmethod
    def create_strategy(cls, uri: Optional[str]) -> FilerStrategy:
        """Create appropriate strategy based on URI scheme.

        Args:
            uri (str): The URI string to determine the strategy.

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

        strategy_class: type[FilerStrategy] = (
            ContentFilerStrategy
            if scheme is None
            else cls.STRATEGY_MAP.get(scheme, LocalFilerStrategy)
        )

        return strategy_class()
