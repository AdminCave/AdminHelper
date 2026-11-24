# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central logging configuration: ``ah_common.logging_config``, shared by the server and
the monitoring service. This module stays the import path (tests patch
``configure_logging`` here)."""

from ah_common.logging_config import configure_logging

__all__ = ["configure_logging"]
