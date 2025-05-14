"""Logging configuration for the core module."""

import logging
import sys

from poiesis.constants import get_poiesis_constants

constant = get_poiesis_constants()

# ANSI escape codes for colors
LOG_COLORS = {
    "DEBUG": "\033[94m",  # Blue
    "INFO": "\033[92m",  # Green
    "WARNING": "\033[93m",  # Yellow
    "ERROR": "\033[91m",  # Red
    "CRITICAL": "\033[95m",  # Magenta
    "RESET": "\033[0m",  # Reset
}


class ColorFormatter(logging.Formatter):
    """Color formatter for logging.

    Args:
        logging.Formatter: The formatter to use.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log message.

        Args:
            record: The log record to format.

        Returns:
            The formatted log message.
        """
        log_color = LOG_COLORS.get(record.levelname, "")
        reset_color = LOG_COLORS["RESET"]

        fmt = self._style._fmt

        colored_levelname = f"{log_color}%(levelname)s{reset_color}"
        colored_timestamp = f"{log_color}%(asctime)s{reset_color}"

        colored_fmt = fmt.replace("%(levelname)s", colored_levelname)
        colored_fmt = colored_fmt.replace("%(asctime)s", colored_timestamp)

        self._style._fmt = colored_fmt
        formatted_message = super().format(record)

        self._style._fmt = fmt

        return formatted_message


def setup_logging(level: str | None = None) -> None:
    """Set up colorful logging configuration for the core module.

    Args:
        level: Optional logging level. If not provided, defaults to INFO.
    """
    if level is None:
        level = constant.LOG_LEVEL

    formatter = ColorFormatter(
        "%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    core_logger = logging.getLogger("poiesis.core")
    core_logger.setLevel(level)
    core_logger.handlers.clear()
    core_logger.propagate = False
    core_logger.addHandler(console_handler)
