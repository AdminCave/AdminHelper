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
until assigned to a server (template_sync.apply_template).

Each built-in carries a version; a changed definition ships as a new version.
A row remembers the version and the hash of the definitions last rolled out to
it: if its definitions still match that hash, the startup moves it to a newer
shipped version and syncs it (reconcile_builtin_templates); an edited row keeps
its definitions and only shows the update until the user takes it
(apply_builtin_update)."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models import MonitorSeedState, MonitorTemplate
from app.schemas import TemplateAlertDef, TemplateCheckDef
from app.template_sync import record_override_baseline, sync_template

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

# Prediction pairs with the static disk thresholds: warns ~a day before a
# disk runs full instead of only at 80/90 % (severity 'warning' — a forecast
# has lead time by definition and must not page the critical chain).
_DISK_FORECAST = {
    "def_id": "disk-forecast",
    "name": "Disk Forecast",
    "description": "Predicts time-until-full from the recent fill rate.",
    "check_type": "disk_forecast",
    "config": {"server_id": "{{server_id}}"},
    "interval": "1h",
    "severity": "warning",
    "consecutive_fails": 1,
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
        "version": 1,
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
            _DISK_FORECAST,
        ],
        "alert_definitions": [],
    },
    {
        "slug": "windows-base",
        "version": 1,
        "name": "Windows Server — Standard",
        "description": "Baseline monitoring for Windows servers: heartbeat, resources and SMART.",
        "check_definitions": [_AGENT_HEARTBEAT, _AGENT_RESOURCES, _SMART_HEALTH, _DISK_FORECAST],
        "alert_definitions": [],
    },
    {
        "slug": "proxmox-host",
        "version": 1,
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
        "version": 1,
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
        "version": 1,
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

# The definitions hash of version 1 of each built-in, frozen. A row seeded before
# built-ins had versions carries no hash; it got the definitions of version 1, and
# reconcile compares it with these, not with whatever ships now, so an unedited
# row still follows a later version. They stand for what version 1 shipped: never
# change them, not even when a built-in gets a new version.
BUILTIN_V1_HASHES = {
    "linux-base": "fda790008184ed153f4734a916746a1ed971edb57570b99dbc49d4195a8ecf13",
    "windows-base": "4be77f8ba5a16bc1857dfcf0b2c5ae634967e7d35b97d837a70769ca36b98e70",
    "proxmox-host": "e76eb40daf8b1dffac8dce22b6d174fd25e7eaa44c515810b4aad092260c8b98",
    "docker-host": "a54b94104244cb22a229e2c67501f546300e40886c552189466c1f3f89cf0d19",
    "zfs-storage": "2cb8243af6f0e31ac72ae4c526b601a4dd7480408f624d390e83ebc24d0d6932",
}


def _without_defaults(schema: type[BaseModel], definition: dict) -> dict:
    """A definition without the keys that hold their schema default. The template
    router stores every field (model_dump), the shipped definitions leave the
    defaults out; and a new optional field in the schema must not change the
    hash stored in every install."""
    defaults = {
        name: field.get_default(call_default_factory=True)
        for name, field in schema.model_fields.items()
        if not field.is_required()
    }
    return {k: v for k, v in definition.items() if not (k in defaults and v == defaults[k])}


def canonical_definitions(
    check_definitions: list[dict], alert_definitions: list[dict]
) -> list[list[dict]]:
    """[check_definitions, alert_definitions] without the keys at their schema
    default: the form the hash covers and the update comparison shows, so two
    definitions look the same exactly when they hash the same."""
    return [
        [_without_defaults(TemplateCheckDef, d) for d in check_definitions],
        [_without_defaults(TemplateAlertDef, d) for d in alert_definitions],
    ]


def definitions_hash(check_definitions: list[dict], alert_definitions: list[dict]) -> str:
    """sha256 over the canonical JSON of [check_definitions, alert_definitions].

    Without the keys at their schema default: the desktop editor sends every
    definition back on each save, a rename included, and an untouched built-in
    must keep its hash. Name and description are not part of it, a renamed
    built-in keeps following new versions."""
    canonical = json.dumps(
        canonical_definitions(check_definitions, alert_definitions),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _shipped_hash(tpl: dict) -> str:
    return definitions_hash(tpl["check_definitions"], tpl["alert_definitions"])


def shipped_builtin(slug: str | None) -> dict | None:
    """The shipped built-in with this slug; None for a user template."""
    return next((tpl for tpl in BUILTIN_TEMPLATES if tpl["slug"] == slug), None)


def builtin_edited(template: MonitorTemplate) -> bool:
    """Whether a built-in's definitions differ from those last rolled out to it."""
    if template.builtin_hash is None:
        return False
    current = definitions_hash(
        json.loads(template.check_definitions or "[]"),
        json.loads(template.alert_definitions or "[]"),
    )
    return current != template.builtin_hash


def builtin_update_available(template: MonitorTemplate) -> bool:
    """Whether a newer version of a built-in ships than the one rolled out to it."""
    tpl = shipped_builtin(template.builtin_slug)
    return (
        tpl is not None
        and template.builtin_version is not None
        and tpl["version"] > template.builtin_version
    )


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
                builtin_version=tpl["version"],
                builtin_hash=_shipped_hash(tpl),
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


def _lock_builtin(db: Session, template_id: str) -> MonitorTemplate | None:
    """The template row under its row lock, read fresh from the database.

    Every rollout decides on this: a second one at the same time (a second
    monitoring instance starting, a user taking the update during a startup)
    waits for the lock and then sees the version the first one rolled out,
    instead of syncing the same update again and creating the new checks twice.
    with_for_update is a no-op on sqlite (tests); the real lock is on Postgres."""
    return (
        db.query(MonitorTemplate)
        .filter(MonitorTemplate.id == template_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def _roll_out(db: Session, template: MonitorTemplate, tpl: dict) -> dict:
    """Give a built-in the shipped definitions, version and hash and sync it to
    its servers (commits, which releases the row lock); the fields a user changed
    on a check stay (template_sync). Name and description stay as well. Returns
    the result of sync_template."""
    template.check_definitions = json.dumps(tpl["check_definitions"])
    template.alert_definitions = json.dumps(tpl["alert_definitions"])
    template.builtin_version = tpl["version"]
    template.builtin_hash = _shipped_hash(tpl)
    result = sync_template(db, template)
    logger.info(
        "Standard template '%s' updated to version %d on %d server(s)",
        tpl["slug"],
        tpl["version"],
        result["servers"],
    )
    return result


def reconcile_builtin_templates(db: Session) -> int:
    """Move every unedited built-in to its shipped version and sync it to its
    servers; the fields a user changed on a check stay (template_sync). Name and
    description stay as well. Returns the number of templates updated.

    A row seeded before built-ins had versions gets version 1 and the frozen hash
    of version 1 first; where its definitions differ, it counts as edited.
    Without the override baseline nothing is rolled out (it raises)."""
    # Before the row lock: the baseline commits, and it has to compare with the
    # definitions from before the rollout.
    record_override_baseline(db)
    template_ids = [
        template_id
        for (template_id,) in db.query(MonitorTemplate.id)
        .filter(MonitorTemplate.builtin_slug.isnot(None))
        .order_by(MonitorTemplate.id)
    ]
    updated = 0
    for template_id in template_ids:
        template = _lock_builtin(db, template_id)
        tpl = shipped_builtin(template.builtin_slug) if template is not None else None
        if tpl is None:
            db.rollback()
            continue
        if template.builtin_hash is None:
            # Rows seeded before versions got their definitions from version 1, so
            # they compare with its frozen hash: unedited, such a row follows a later
            # version as well. A slug without one shipped only after the versions;
            # the shipped hash stands for it.
            template.builtin_version = 1
            template.builtin_hash = BUILTIN_V1_HASHES.get(tpl["slug"], _shipped_hash(tpl))
        if not builtin_update_available(template) or builtin_edited(template):
            db.commit()
            continue
        _roll_out(db, template, tpl)
        updated += 1
    return updated


def apply_builtin_update(db: Session, template_id: str) -> dict | None:
    """Move a built-in to its shipped version on the user's request, edited or
    not; the definitions the user changed on the template go, the fields changed
    on a check stay. Returns the result of sync_template, or None when no newer
    version ships, also when a concurrent rollout got there first."""
    record_override_baseline(db)  # before the row lock, as in reconcile
    template = _lock_builtin(db, template_id)
    tpl = shipped_builtin(template.builtin_slug) if template is not None else None
    if tpl is None or not builtin_update_available(template):
        db.rollback()
        return None
    return _roll_out(db, template, tpl)
