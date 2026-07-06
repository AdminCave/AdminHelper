# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central logging configuration.

Without this the server had no logging setup at all: the stdlib root logger
defaults to WARNING with the bare "last resort" handler, so every ``logger.info``
was silently dropped and warnings/errors printed without a timestamp. We route
all loggers — the app's ``adminhelper.*`` ones and uvicorn's — through a single
timestamped stderr handler, so ``docker compose logs`` shows the full picture.
Logs go to stderr (not stdout) so a subprocess that uses stdout as an IPC channel
— the hook script worker — is never corrupted by a stray log line; docker compose
logs captures stderr all the same.

Format is human-readable on purpose (not JSON): operators read it directly via
``docker compose logs``. The ``[%(process)d]`` PID field disambiguates the
interleaved lines when ``WEB_CONCURRENCY`` > 1 runs several web workers plus the
scheduler (a per-request correlation ID is a follow-up). The level is taken
from ``LOG_LEVEL`` (default INFO); an unknown value falls back to INFO rather
than crashing startup.
"""

import logging.config
import os

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(process)d] %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level() -> str:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    # getLevelName returns an int for known names, the "Level X" string otherwise.
    if not isinstance(logging.getLevelName(level), int):
        return "INFO"
    return level


def configure_logging() -> None:
    """Install a single timestamped stdout handler for the app and uvicorn."""
    level = _resolve_level()
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": _LOG_FORMAT, "datefmt": _DATE_FORMAT},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stderr",
                },
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                # uvicorn installs its own handlers; re-route them through ours so
                # access/error lines share the app's timestamped format.
                "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
            },
        }
    )
