# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes generated FRP configs into the shared volume for the frps container."""

import logging
from pathlib import Path

from app.core.config import FRP_CONFIG_DIR
from app.modules.frp.config_generator import generate_frps_toml

logger = logging.getLogger(__name__)


def write_frps_config(config) -> Path:
    """Writes frps.toml into FRP_CONFIG_DIR. Returns the file path."""
    toml = generate_frps_toml(config)
    path = FRP_CONFIG_DIR / "frps.toml"
    path.write_text(toml, encoding="utf-8")
    logger.info("frps.toml geschrieben: %s", path)
    return path


def remove_frps_config() -> None:
    """Removes frps.toml from FRP_CONFIG_DIR."""
    path = FRP_CONFIG_DIR / "frps.toml"
    if path.exists():
        path.unlink()
        logger.info("frps.toml entfernt: %s", path)
