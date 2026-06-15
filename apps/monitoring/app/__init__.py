# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Configure logging here, in the package __init__, so it runs before any
# app.* submodule is imported — capturing even import-time messages (e.g. the
# MONITOR_API_KEY notice in app.core.config) with the timestamped format.
from app.core.logging_config import configure_logging

configure_logging()
