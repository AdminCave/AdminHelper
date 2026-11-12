# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent's plan (R-1223): the probes it runs, the markers its discovery looks for,
whether it scans in this run and whether it sends the error lines of failed services."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.catalog.loader import Catalog, get_catalog
from app.check_configs import ProbeConfig
from app.core.time import utcnow_naive
from app.discovery import scan_due
from app.models import MonitorCheck, MonitorDiscovery, MonitorServiceInventory

logger = logging.getLogger(__name__)

PLAN_VERSION = 1


def build_plan(
    db: Session,
    server_id: str,
    *,
    catalog: Catalog | None = None,
    now: datetime | None = None,
) -> dict:
    catalog = catalog or get_catalog()
    return {
        "plan_version": PLAN_VERSION,
        "catalog_version": catalog.version,
        "scan": scan_due(db.get(MonitorDiscovery, server_id), now or utcnow_naive()),
        "discovery": {"markers": _markers(catalog)},
        "probes": _probes(db, server_id),
        "service_logs": _service_logs(db, server_id),
    }


def _service_logs(db: Session, server_id: str) -> bool:
    """R-1226: the agent sends the error lines of failed services unless the server's
    switch is off; a server without a row has the column default, on."""
    row = db.get(MonitorServiceInventory, server_id)
    return row is None or row.log_lines is not False


def _markers(catalog: Catalog) -> list[dict]:
    markers = [m for module in catalog.modules.values() for m in module.detect.markers]
    return [
        {"id": m.id, "paths": list(m.paths), "packages": list(m.packages)}
        for m in sorted(markers, key=lambda m: m.id)
    ]


def _probes(db: Session, server_id: str) -> list[dict]:
    checks = (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorCheck.check_type == "probe",
            MonitorCheck.enabled.is_(True),
            # R-1252: the agent runs only the probes a module of the catalog brought.
            MonitorCheck.module_id.isnot(None),
        )
        .order_by(MonitorCheck.id)
        .all()
    )
    probes = []
    for check in checks:
        # The plan is what the agent runs: a stored config is checked again against
        # today's rules, so one that no longer holds is never sent.
        try:
            config = ProbeConfig.model_validate(json.loads(check.config or "{}"))
        # ValueError covers broken JSON and pydantic's ValidationError alike.
        except ValueError as exc:
            logger.warning("Probe check %s left out of the plan: %s", check.id, type(exc).__name__)
            continue
        probes.append(_probe(check.id, config))
    return probes


def _probe(check_id: str, config: ProbeConfig) -> dict:
    target = config.target
    credential = config.credential
    return {
        "id": check_id,
        "sensor": config.sensor,
        "interval_s": config.interval_s,
        "timeout_s": config.timeout_s,
        "target": None
        if target is None
        else {
            "kind": target.kind,
            "name": target.name,
            "port_hint": target.port_hint,
            "scheme": target.scheme,
        },
        "params": config.params,
        "fields": config.fields,
        "credential": None
        if credential is None
        else {"ref": credential.ref, "use": credential.use},
    }
