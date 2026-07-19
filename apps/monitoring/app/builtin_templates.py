# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Built-in standard templates, seeded once at startup.

A fresh install monitored nothing until an operator hand-built checks; these
templates make a newly-assigned server monitored out of the box. Thresholds
are distilled from the stock templates/health configs of Zabbix ("Linux by
Zabbix agent"), Netdata and Checkmk plus Backblaze's SMART failure statistics
(see docs/features/monitoring-overhaul.md). Plugin checks (Proxmox/Docker/ZFS)
live in separate opt-in templates on purpose: on a host without the subsystem
they would sit at 'unknown' forever.

Seeding is tombstone-guarded via monitor_seed_state: a slug is seeded at most
once — user edits and deletions are never overridden, and later releases can
add new built-ins without touching existing ones. Templates create no checks
until assigned to a server (template_sync.apply_template)."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.models import MonitorSeedState, MonitorTemplate

logger = logging.getLogger("monitor.seed")

# Heartbeat: stale after 3 missed 5-minute push intervals; consecutive_fails 1
# because stale_minutes already damps (the scheduler re-checks every 5m).
_AGENT_HEARTBEAT = {
    "def_id": "agent-heartbeat",
    "name": "Agent Heartbeat",
    "description": "Alerts when the agent has stopped reporting.",
    "check_type": "agent_ping",
    "config": {"server_id": "{{server_id}}", "stale_minutes": 15},
    "interval": "5m",
    "severity": "critical",
    "consecutive_fails": 1,
}

# Resources: warn/crit pairs from the Zabbix/Netdata consensus (CPU 90/95,
# RAM 90/98, disk 80/90); consecutive_fails 3 on a 5-minute push cadence means
# the condition must hold ~15 minutes — the standard anti-flap window.
_AGENT_RESOURCES = {
    "def_id": "system-resources",
    "name": "System Resources",
    "description": "CPU, memory, disk and temperature thresholds.",
    "check_type": "agent_resources",
    "config": {
        "cpu_warn": 90,
        "cpu_crit": 95,
        "memory_warn": 90,
        "memory_crit": 98,
        "disk_warn": 80,
        "disk_crit": 90,
        "temp_warn": 80,
        "temp_crit": 95,
    },
    "interval": "5m",
    "severity": "critical",
    "consecutive_fails": 3,
}

_SMART_HEALTH = {
    "def_id": "smart-health",
    "name": "SMART Health",
    "description": "Disk SMART attributes (checker defaults, Backblaze-validated).",
    "check_type": "smart_health",
    "config": {},
    "interval": "5m",
    "severity": "critical",
    "consecutive_fails": 2,
}

BUILTIN_TEMPLATES: list[dict] = [
    {
        "slug": "linux-base",
        "name": "Linux Server — Standard",
        "description": "Baseline monitoring for Linux servers: heartbeat, resources, "
        "systemd service health and SMART.",
        "check_definitions": [
            _AGENT_HEARTBEAT,
            _AGENT_RESOURCES,
            {
                "def_id": "service-health",
                "name": "Service Health",
                "description": "Failed and enabled-but-inactive systemd units.",
                "check_type": "service_process",
                "config": {"mode": "auto"},
                "interval": "5m",
                "severity": "critical",
                "consecutive_fails": 2,
            },
            _SMART_HEALTH,
        ],
        "alert_definitions": [],
    },
    {
        "slug": "windows-base",
        "name": "Windows Server — Standard",
        "description": "Baseline monitoring for Windows servers: heartbeat, resources and SMART.",
        "check_definitions": [_AGENT_HEARTBEAT, _AGENT_RESOURCES, _SMART_HEALTH],
        "alert_definitions": [],
    },
    {
        "slug": "proxmox-host",
        "name": "Proxmox Host",
        "description": "Backup freshness for Proxmox VMs and containers.",
        "check_definitions": [
            {
                "def_id": "proxmox-backup",
                "name": "Proxmox Backups",
                "description": "Alerts when a guest has no recent backup.",
                "check_type": "proxmox_backup",
                "config": {"max_backup_age_hours": 26},
                "interval": "5m",
                "severity": "warning",
                "consecutive_fails": 1,
            }
        ],
        "alert_definitions": [],
    },
    {
        "slug": "docker-host",
        "name": "Docker Host",
        "description": "Container state and health-check status.",
        "check_definitions": [
            {
                "def_id": "docker-health",
                "name": "Docker Health",
                "description": "Exited/unhealthy containers.",
                "check_type": "docker_health",
                "config": {},
                "interval": "5m",
                "severity": "critical",
                "consecutive_fails": 2,
            }
        ],
        "alert_definitions": [],
    },
    {
        "slug": "zfs-storage",
        "name": "ZFS Storage",
        "description": "Pool health and capacity.",
        "check_definitions": [
            {
                "def_id": "zfs-health",
                "name": "ZFS Health",
                "description": "Pool state and capacity thresholds.",
                "check_type": "zfs_health",
                "config": {"capacity_warn": 80, "capacity_crit": 90},
                "interval": "5m",
                "severity": "critical",
                "consecutive_fails": 2,
            }
        ],
        "alert_definitions": [],
    },
]


def seed_builtin_templates(db: Session) -> int:
    """Create every built-in template whose slug was never seeded before.

    Returns the number of templates created. Idempotent: the tombstone check
    against monitor_seed_state (not against existing templates) means a
    user-deleted built-in stays deleted and a user-edited one stays edited."""
    seeded = {slug for (slug,) in db.query(MonitorSeedState.slug).all()}
    created = 0
    for tpl in BUILTIN_TEMPLATES:
        if tpl["slug"] in seeded:
            continue
        db.add(
            MonitorTemplate(
                id=str(uuid.uuid4()),
                name=tpl["name"],
                description=tpl["description"],
                builtin_slug=tpl["slug"],
                check_definitions=json.dumps(tpl["check_definitions"]),
                alert_definitions=json.dumps(tpl["alert_definitions"]),
            )
        )
        db.add(MonitorSeedState(slug=tpl["slug"]))
        created += 1
    if created:
        db.commit()
        logger.info("%d Standard-Template(s) geseedet", created)
    return created
