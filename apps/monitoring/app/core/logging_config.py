# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central logging configuration.

Replaces the previous one-line ``basicConfig`` so the monitoring service shares
the server's format: all loggers — the app's ``monitor.*`` ones and uvicorn's —
go through a single timestamped stderr handler, visible via ``docker compose
logs`` (stderr, not stdout — same convention as the server, where stdout is left
free for subprocess IPC). Format is human-readable on purpose (not JSON); the level is taken from
``LOG_LEVEL`` (default INFO), an unknown value falls back to INFO rather than
crashing startup.

This module is deliberately duplicated from the server: the two services share
no common Python package, so a copied ~40-line helper beats a premature shared
library (YAGNI).
"""

import logging.config
import os

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
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
