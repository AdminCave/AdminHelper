# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Central check-type taxonomy — single source of truth.

A neutral module so the scheduler, check engine, agent router and checks router
all import the type set from one place. The set was previously spread across
schemas.VALID_CHECK_TYPES and scheduler.PUSH_ONLY_TYPES (and could drift, e.g. a
new type added to one but not the other); deriving both from one table keeps them
in lockstep. It also lets scheduler and check_engine import at module level
instead of via function-local imports (which only avoided a real scheduler <->
check_engine import cycle by importing late).
"""

from __future__ import annotations

# push_only: evaluated only by the agent report endpoint, not the scheduler.
# agent_ping is deliberately NOT push_only — the scheduler evaluates it (it checks
# whether the agent has gone stale).
CHECK_TYPES: dict[str, dict[str, bool]] = {
    "ping": {"push_only": False},
    "tcp": {"push_only": False},
    "http": {"push_only": False},
    "agent_ping": {"push_only": False},
    "agent_resources": {"push_only": True},
    "service_process": {"push_only": True},
    "proxmox_backup": {"push_only": True},
    "zfs_health": {"push_only": True},
    "docker_health": {"push_only": True},
    "smart_health": {"push_only": True},
}

VALID_CHECK_TYPES = set(CHECK_TYPES)
PUSH_ONLY_TYPES = {t for t, meta in CHECK_TYPES.items() if meta["push_only"]}
