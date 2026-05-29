"""Logging configuration for deploy-to-s3.

Exposes :func:`configure_logging` to initialise handlers and
:func:`get_logger` to obtain a named logger anywhere in the package.
"""

import functools
import logging
import sys
from pathlib import Path
from typing import Literal

_LOG_FORMAT = (
    "%(asctime)s - %(levelname)-5s - %(name)s - %(filename)s:%(lineno)d - %(message)s"
)
_LOG_FILE = Path("logs") / "app.log"
LogLevel = Literal[logging.INFO, logging.DEBUG]
_ALLOWED_LOG_LEVELS = frozenset[int]({logging.INFO, logging.DEBUG})


@functools.cache
def configure_logging(*, level: LogLevel) -> None:
    """Configure application logging. Call once before :func:`get_logger`.

    Args:
        level: ``logging.INFO`` or ``logging.DEBUG`` only.

    Raises:
        ValueError: If ``level`` is not INFO or DEBUG.
    """
    if level not in _ALLOWED_LOG_LEVELS:
        msg = f"level must be logging.INFO or logging.DEBUG, got {level!r}"
        raise ValueError(msg)

    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
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
