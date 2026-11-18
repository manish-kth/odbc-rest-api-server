"""Application logging configuration.

Configured from environment variables at app import time:

  LOG_LEVEL   DEBUG | INFO (default) | WARNING | ERROR
  LOG_FORMAT  text  (default, human-readable) | json (one JSON object per line)

Only the application logger tree (``api`` and its children) is touched —
uvicorn's own loggers (`uvicorn`, `uvicorn.access`, `uvicorn.error`) are
left alone so their access logs continue to work as configured by uvicorn.
"""

import json
import logging
import os
import sys


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    """Initialise the ``api`` logger. Safe to call multiple times."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("LOG_FORMAT", "text").lower()

    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    logger = logging.getLogger("api")
    logger.handlers = [handler]
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False  # don't double-print via the root logger
