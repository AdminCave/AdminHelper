# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central check-type taxonomy.

A neutral module so the scheduler and the check engine can both import the
push-only set at module level. Previously each imported it from the other via a
function-local import — the only thing keeping a real scheduler <-> check_engine
import cycle from crashing at import time.
"""

from __future__ import annotations

# Agent push checks are evaluated only by the agent report endpoint, not by the
# scheduler. agent_ping is the exception: it checks whether the agent is stale.
PUSH_ONLY_TYPES = {
    "agent_resources",
    "service_process",
    "docker_health",
    "proxmox_backup",
    "zfs_health",
    "smart_health",
}
