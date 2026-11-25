# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central logging configuration of both services.

Without it the stdlib root logger defaults to WARNING with the bare "last resort"
handler, so every ``logger.info`` was dropped and warnings printed without a
timestamp. All loggers — each service's own (``adminhelper.*``, ``monitor.*``) and
uvicorn's — go through a single timestamped stderr handler, so ``docker compose
logs`` shows the full picture. Logs go to stderr (not stdout) so a subprocess that
uses stdout as an IPC channel — the server's hook script worker — is never
corrupted by a stray log line.

Format is human-readable on purpose (not JSON): operators read it directly via
``docker compose logs``. The ``[%(process)d]`` PID field disambiguates interleaved
lines of several worker processes. The level is taken from ``LOG_LEVEL`` (default
INFO); an unknown value stops the start with a ``ConfigError`` (``ah_common.env``).
"""

import logging.config
import os

from ah_common.env import ConfigError

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(process)d] %(name)s %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_level() -> str:
    raw = os.environ.get("LOG_LEVEL", "")
    level = raw.strip().upper() or "INFO"
    # A fixed list, not getLevelName: uvicorn registers TRACE, and any package may add a name.
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError(f"LOG_LEVEL={raw!r} is not one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
    return level


def configure_logging() -> None:
    """Install a single timestamped stderr handler for the app and uvicorn."""
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
                # httpx logs every request with its full URL on INFO, httpcore traces it on
                # DEBUG; a hook or webhook URL can carry a credential in its path or query.
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
            },
        }
    )
