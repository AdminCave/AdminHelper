# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog, discovery and the findings inbox (R-1223, docs/features/arch-monitoring-module.md)."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import module_sync
from app.catalog.loader import Catalog, get_catalog
from app.core.auth import require_internal
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.pagination import paginate
from app.core.time import iso_utc, utcnow_naive
from app.models import MonitorCheck, MonitorDiscovery, MonitorFinding
from app.schemas import AdoptAllOut, AdoptOut, CatalogOut, DiscoveryOut, FindingOut

router = APIRouter()


def _finding_out(finding: MonitorFinding, checks: list[MonitorCheck], catalog: Catalog) -> dict:
    module = catalog.modules.get(finding.module_id)
    keys = set() if module is None else {check.key for check in module.checks}
    try:
        summary = json.loads(finding.summary)
    except (TypeError, ValueError):
        summary = None
    return {
        "id": finding.id,
        "serverId": finding.server_id,
        "moduleId": finding.module_id,
        "moduleName": None if module is None else module.name,
        "instanceKey": finding.instance_key,
        "kind": finding.kind,
        "status": finding.status,
        "summary": summary,
        "catalogVersion": finding.catalog_version,
        "firstSeen": iso_utc(finding.first_seen),
        "lastSeen": iso_utc(finding.last_seen),
        "decidedAt": iso_utc(finding.decided_at),
        "silentChecks": [c.id for c in checks if c.silent],
        "droppedChecks": [c.id for c in checks if c.module_check_key not in keys],
    }


def _adopt_out(db: Session, result: module_sync.AdoptResult, catalog: Catalog) -> dict:
    finding = result.finding
    return {
        "finding": _finding_out(finding, module_sync.instance_checks(db, finding), catalog),
        "enabledChecks": result.enabled,
        "disabledChecks": result.disabled,
        "skippedChecks": result.skipped,
    }


def _discovery_out(server_id: str, row: MonitorDiscovery | None) -> dict:
    if row is None:
        return {
            "serverId": server_id,
            "scannedAt": None,
            "nextScanAt": None,
            "scanRequestedAt": None,
            "inventory": {},
            "credentials": [],
        }
    return {
        "serverId": server_id,
        "scannedAt": iso_utc(row.scanned_at),
        "nextScanAt": iso_utc(row.next_scan_at),
        "scanRequestedAt": iso_utc(row.scan_requested_at),
        "inventory": json.loads(row.inventory),
        "credentials": sorted(json.loads(row.credentials)),
    }


@router.get("/catalog", response_model=CatalogOut, dependencies=[Depends(require_internal)])
def get_module_catalog():
    """The module catalog: modules with their checks and card figures."""
    catalog = get_catalog()
    return {
        "version": catalog.version,
        "modules": [
            {
                "id": module.id,
                "name": module.name,
                "version": module.version,
                "description": module.description,
                "instance": module.instance,
                "checks": [
                    {
                        "key": check.key,
                        "name": check.name,
                        "sensor": check.sensor,
                        "interval": check.interval,
                        "fields": check.fields,
                        "testObject": check.test_object,
                        "credential": None
                        if check.credential is None
                        else {"slot": check.credential.slot, "use": check.credential.use},
                    }
                    for check in module.checks
                ],
                "card": [
                    {"checkKey": item.check_key, "field": item.field, "label": item.label}
                    for item in module.card
                ],
            }
            for module in sorted(catalog.modules.values(), key=lambda m: m.id)
        ],
    }


@router.get(
    "/discovery/{server_id}", response_model=DiscoveryOut, dependencies=[Depends(require_internal)]
)
def get_discovery(server_id: str, db: Session = Depends(get_db)):
    """The server's last scan, a pending "scan now" and the credential references its
    agent holds."""
    return _discovery_out(server_id, db.get(MonitorDiscovery, server_id))


@router.post(
    "/discovery/{server_id}/scan",
    response_model=DiscoveryOut,
    dependencies=[Depends(require_internal)],
)
def request_scan(server_id: str, db: Session = Depends(get_db)):
    """Scan now: the agent's next plan asks for a discovery. Pressing it again while
    it is pending changes nothing."""
    now = utcnow_naive()
    row = db.get(MonitorDiscovery, server_id)
    if row is None:
        db.add(MonitorDiscovery(server_id=server_id, scan_requested_at=now))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # a report created the row meanwhile
        row = db.get(MonitorDiscovery, server_id)
    if row.scan_requested_at is None:
        row.scan_requested_at = now
        db.commit()
    return _discovery_out(server_id, row)


@router.get(
    "/findings",
    response_model=list[FindingOut],
    dependencies=[Depends(require_internal)],
)
def list_findings(
    response: Response,
    server_id: str | None = Query(None),
    status: Literal["open", "adopted", "dismissed"] | None = Query(None),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: Annotated[Offset, Query()] = 0,
    db: Session = Depends(get_db),
):
    """The findings inbox, optionally of one server and in one status."""
    q = db.query(MonitorFinding)
    if server_id:
        q = q.filter(MonitorFinding.server_id == server_id)
    if status:
        q = q.filter(MonitorFinding.status == status)
    order = (MonitorFinding.server_id, MonitorFinding.module_id, MonitorFinding.instance_key)
    findings = paginate(q.order_by(*order), response, limit, offset).all()
    checks: dict[tuple[str, str, str], list[MonitorCheck]] = defaultdict(list)
    if findings:
        rows = (
            db.query(MonitorCheck)
            .filter(
                MonitorCheck.server_id.in_({f.server_id for f in findings}),
                MonitorCheck.module_id.isnot(None),
            )
            .order_by(MonitorCheck.created_at, MonitorCheck.id)
        )
        for row in rows:
            checks[(row.server_id, row.module_id, row.module_instance)].append(row)
    catalog = get_catalog()
    return [
        _finding_out(f, checks[(f.server_id, f.module_id, f.instance_key)], catalog)
        for f in findings
    ]


@router.post(
    "/findings/adopt-all", response_model=AdoptAllOut, dependencies=[Depends(require_internal)]
)
def adopt_all_findings(server_id: str = Query(...), db: Session = Depends(get_db)):
    """Adopts every open finding of the server."""
    catalog = get_catalog()
    results, failed = module_sync.adopt_all(db, server_id, catalog=catalog)
    return {"adopted": [_adopt_out(db, r, catalog) for r in results], "failed": failed}


@router.post(
    "/findings/{finding_id}/adopt",
    response_model=AdoptOut,
    dependencies=[Depends(require_internal)],
)
def adopt_finding(finding_id: str, db: Session = Depends(get_db)):
    """Adopts a finding: creates the instance's checks or switches them on; a "gone"
    finding switches them off. Never deletes a check."""
    catalog = get_catalog()
    try:
        result = module_sync.adopt(db, finding_id, catalog=catalog)
    except module_sync.AdoptError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Finding not found")
    return _adopt_out(db, result, catalog)


@router.post(
    "/findings/{finding_id}/dismiss",
    response_model=FindingOut,
    dependencies=[Depends(require_internal)],
)
def dismiss_finding(finding_id: str, db: Session = Depends(get_db)):
    """Dismisses a finding; it stays dismissed until it changes."""
    finding = module_sync.dismiss(db, finding_id)
    if finding is None:
        raise HTTPException(404, "Finding not found")
    return _finding_out(finding, module_sync.instance_checks(db, finding), get_catalog())
