# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Taking over what discovery found (R-1223, docs/features/arch-monitoring-module.md).

Adopting a finding turns the catalog checks of its module into probe checks bound to
the instance, or switches them on again; adopting a "gone" finding switches them off.
Nothing here deletes a check. At start-up, adopted instances follow a changed catalog:
checks the update added start silent and the finding turns "changed", so the admin
decides when they alert."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.catalog.loader import Catalog, get_catalog
from app.catalog.model import Check, Module
from app.check_configs import ProbeConfig
from app.core.time import utcnow_naive
from app.discovery import image_matches, image_repo
from app.models import MonitorCheck, MonitorDiscovery, MonitorFinding, MonitorState
from app.template_sync import SchedulerAction, apply_scheduler_actions

logger = logging.getLogger(__name__)

# The catalog's probe intervals in the notation of a check row.
_INTERVAL_TEXT = {300: "5m", 900: "15m", 3600: "1h", 86400: "24h"}


class AdoptError(Exception):
    """The finding cannot be adopted as it stands."""


@dataclass
class AdoptResult:
    finding: MonitorFinding
    enabled: list[str] = field(default_factory=list)  # check ids now alerting
    disabled: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"key", "reason"}


def instance_checks(db: Session, finding: MonitorFinding) -> list[MonitorCheck]:
    """Every check the finding's module brought to its instance, in creation order."""
    return (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == finding.server_id,
            MonitorCheck.module_id == finding.module_id,
            MonitorCheck.module_instance == finding.instance_key,
        )
        .order_by(MonitorCheck.created_at, MonitorCheck.id)
        .all()
    )


def _summary(finding: MonitorFinding) -> dict:
    try:
        summary = json.loads(finding.summary)
    except (TypeError, ValueError):
        return {}
    return summary if isinstance(summary, dict) else {}


def _containers(db: Session, server_id: str) -> list[dict]:
    row = db.get(MonitorDiscovery, server_id)
    if row is None:
        return []
    return json.loads(row.inventory).get("containers", [])


def _target_name(
    module: Module, kind: str, service: str, key: str, summary: dict, containers: list[dict]
) -> tuple[str | None, str | None]:
    """(the container, unit or process of the instance a check of this kind asks, None)
    or (None, why there is none)."""
    none = f"no {kind} for this instance"
    matched_by = summary.get("matched_by")
    if matched_by is not None:
        # Found outside its own kind of instance: only an unambiguous unit or process of
        # the match can be asked.
        names = [m.split(":", 1)[1] for m in matched_by if m.startswith(kind + ":")]
        return (names[0], None) if len(names) == 1 else (None, none)
    if kind == module.instance:
        return key, None
    if kind == "container" and module.instance == "compose_project":
        if "container" in summary:
            # A container of the module outside any project: it has no other services.
            return (None, none) if service else (summary["container"], None)
        # The name as the last scan saw it; the agent asks this container, and a new
        # name (a rebuilt project) is a changed finding.
        prefixes = [image_repo(p) for p in module.detect.container_images]
        names = sorted(
            c["name"]
            for c in containers
            if c["compose_project"] == key
            and (
                c["compose_service"] == service
                if service
                else image_matches(image_repo(c["image"]), prefixes)
            )
        )
        if len(names) > 1:
            # The check's target must be unambiguous; with several replicas none is picked.
            return None, f"several containers for this instance: {', '.join(names)}"
        return (names[0], None) if names else (None, none)
    return None, none


def probe_config(
    module: Module, check: Check, key: str, summary: dict, containers: list[dict]
) -> tuple[dict | None, str | None]:
    """(the probe config of the catalog check bound to the instance, None) or
    (None, why it cannot be bound)."""
    target = None
    if check.target is not None:
        t = check.target
        name = ""
        port_hint = t.port_hint
        if t.kind == "port":
            if port_hint is None:
                port_hint = summary.get("port")
            if port_hint is None:
                return None, "no port for this instance"
        elif t.kind != "loopback":
            name, why = _target_name(module, t.kind, t.service, key, summary, containers)
            if not name:
                return None, why
        target = {"kind": t.kind, "name": name, "port_hint": port_hint, "scheme": t.scheme}
    config = {
        "sensor": check.sensor,
        "target": target,
        "params": dict(check.params),
        "interval_s": check.interval,
        "timeout_s": check.timeout_s,
        "fields": list(check.fields),
        "rules": [rule.model_dump() for rule in check.rules],
        "credential": None
        if check.credential is None
        else {"ref": f"{module.id}/{key}/{check.credential.slot}", "use": check.credential.use},
        "test_object": check.test_object,
    }
    try:
        ProbeConfig.model_validate(config)
    except ValueError as exc:
        logger.warning(
            "Catalog check %s/%s does not bind to %s: %s", module.id, check.key, key, exc
        )
        return None, "the bound check does not hold"
    return config, None


def _create(
    db: Session,
    finding: MonitorFinding,
    module: Module,
    check: Check,
    summary: dict,
    containers: list[dict],
    *,
    silent: bool,
) -> tuple[MonitorCheck | None, str | None]:
    config, reason = probe_config(module, check, finding.instance_key, summary, containers)
    if config is None:
        return None, reason
    row = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id=finding.server_id,
        name=f"{module.name} ({finding.instance_key}): {check.name}",
        check_type="probe",
        config=json.dumps(config),
        enabled=True,
        interval=_INTERVAL_TEXT[check.interval],
        module_id=module.id,
        module_instance=finding.instance_key,
        module_check_key=check.key,
        silent=silent,
    )
    db.add(row)
    db.add(MonitorState(check_id=row.id, status="pending"))
    return row, None


def _adopt(
    db: Session, finding: MonitorFinding, catalog: Catalog, now: datetime
) -> tuple[AdoptResult, list[SchedulerAction]]:
    result = AdoptResult(finding)
    actions: list[SchedulerAction] = []
    checks = instance_checks(db, finding)
    if finding.kind == "gone":
        for row in checks:
            if row.enabled:
                row.enabled = False
                result.disabled.append(row.id)
                actions.append(("remove", row.id, None, None))
    else:
        module = catalog.modules.get(finding.module_id)
        if module is None:
            raise AdoptError("Module is no longer in the catalog")
        keys = {check.key for check in module.checks}
        for row in checks:
            if row.module_check_key not in keys:
                continue  # dropped from the catalog: stays as the admin left it
            # A new instance is watched whole again (adopting "gone" switched its checks
            # off); on a changed one, a check the admin switched off stays off.
            if finding.kind == "new":
                row.enabled = True
            row.silent = False
            if row.enabled:
                result.enabled.append(row.id)
                actions.append(("add", row.id, row.interval, row.check_type))
        have = {row.module_check_key for row in checks}
        summary = _summary(finding)
        containers = _containers(db, finding.server_id)
        for check in module.checks:
            if check.key in have:
                continue
            row, reason = _create(db, finding, module, check, summary, containers, silent=False)
            if row is None:
                result.skipped.append({"key": check.key, "reason": reason})
                continue
            result.enabled.append(row.id)
            actions.append(("add", row.id, row.interval, row.check_type))
        finding.catalog_version = catalog.version
    finding.status, finding.decided_at = "adopted", now
    return result, actions


def adopt(
    db: Session, finding_id: str, *, catalog: Catalog | None = None, now: datetime | None = None
) -> AdoptResult | None:
    """Adopt one finding; None when there is none with this id. Own commit."""
    finding = (
        db.query(MonitorFinding).filter(MonitorFinding.id == finding_id).with_for_update().first()
    )
    if finding is None:
        return None
    result, actions = _adopt(db, finding, catalog or get_catalog(), now or utcnow_naive())
    db.commit()
    apply_scheduler_actions(actions)
    return result


def adopt_all(
    db: Session, server_id: str, *, catalog: Catalog | None = None, now: datetime | None = None
) -> tuple[list[AdoptResult], list[dict]]:
    """Adopt every open finding of the server: (results, [{"findingId", "reason"}] of
    those that cannot be adopted). One commit."""
    catalog = catalog or get_catalog()
    now = now or utcnow_naive()
    findings = (
        db.query(MonitorFinding)
        .filter(MonitorFinding.server_id == server_id, MonitorFinding.status == "open")
        .order_by(MonitorFinding.module_id, MonitorFinding.instance_key)
        .with_for_update()
        .all()
    )
    results: list[AdoptResult] = []
    failed: list[dict] = []
    actions: list[SchedulerAction] = []
    for finding in findings:
        try:
            result, more = _adopt(db, finding, catalog, now)
        except AdoptError as exc:
            failed.append({"findingId": finding.id, "reason": str(exc)})
            continue
        results.append(result)
        actions.extend(more)
    db.commit()
    apply_scheduler_actions(actions)
    return results, failed


def dismiss(db: Session, finding_id: str, *, now: datetime | None = None) -> MonitorFinding | None:
    """Dismiss a finding until it changes; None when there is none with this id."""
    finding = (
        db.query(MonitorFinding).filter(MonitorFinding.id == finding_id).with_for_update().first()
    )
    if finding is None:
        return None
    finding.status, finding.decided_at = "dismissed", now or utcnow_naive()
    db.commit()
    return finding


def sync_catalog(db: Session, *, catalog: Catalog | None = None) -> int:
    """Bring adopted instances up to a changed catalog; returns how many findings it
    reopened. Runs at start-up before load_all_checks, which schedules what it adds.

    A check the catalog added is created silent; a check it dropped stays. Either makes
    the finding "changed" and open, so the admin sees it and adopting makes the new
    checks alert. A module the catalog no longer has is left alone."""
    catalog = catalog or get_catalog()
    reopened = 0
    findings = (
        db.query(MonitorFinding)
        .filter(
            MonitorFinding.status == "adopted",
            MonitorFinding.kind != "gone",
            MonitorFinding.catalog_version != catalog.version,
        )
        .all()
    )
    for finding in findings:
        module = catalog.modules.get(finding.module_id)
        if module is None:
            continue
        checks = instance_checks(db, finding)
        have = {row.module_check_key for row in checks}
        keys = {check.key for check in module.checks}
        dropped = any(row.enabled and row.module_check_key not in keys for row in checks)
        summary = _summary(finding)
        containers = _containers(db, finding.server_id)
        created = False
        for check in module.checks:
            if check.key in have:
                continue
            row, _ = _create(db, finding, module, check, summary, containers, silent=True)
            created = created or row is not None
        if created or dropped:
            finding.kind, finding.status, finding.decided_at = "changed", "open", None
            reopened += 1
        finding.catalog_version = catalog.version
    db.commit()
    if reopened:
        logger.info("Catalog update: %d adopted module instance(s) changed", reopened)
    return reopened
