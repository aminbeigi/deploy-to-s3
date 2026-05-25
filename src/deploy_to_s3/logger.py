"""Logging configuration for deploy-to-s3.

Exposes :func:`configure_logging` to initialise handlers and
:func:`get_logger` to obtain a named logger anywhere in the package.
"""

import logging
import sys
from pathlib import Path

_LOG_FILE = Path("logs") / "app.log"
_FORMAT = "%(asctime)s - %(levelname)-8s - %(name)s:%(lineno)d - %(message)s"


def configure_logging() -> None:
    """Configure root logger with stdout and file handlers.

    Writes INFO-level records to both stdout and ``logs/app.log``.
    Safe to call multiple times; subsequent calls are no-ops if the root
    logger already has handlers.
    """
    if logging.getLogger().handlers:
        return

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format=_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        ],
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given name.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A logger configured by :func:`configure_logging`.
    """
    return logging.getLogger(name)
