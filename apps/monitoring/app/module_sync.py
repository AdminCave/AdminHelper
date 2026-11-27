# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Taking over what discovery found (R-1223, docs/features/arch-monitoring-module.md).

Adopting a finding turns the catalog checks of its module into probe checks bound to
the instance (central checks of its public name, R-1501), or switches them on again;
adopting a "gone" finding switches them off.
Nothing here deletes a check. At start-up, adopted instances follow a changed catalog:
checks the update added start silent and the finding turns "changed", so the admin
decides when they alert. A check whose catalog definition changed is offered as an
update the same way: adopting writes the new definition (R-1264), nothing rolls it out
by itself."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.catalog.loader import Catalog, get_catalog
from app.catalog.model import Alternative, Check, Module, Rule, rule_problems
from app.check_configs import CENTRAL_SENSORS, CentralConfig, ProbeConfig
from app.core.time import utcnow_naive
from app.discovery import MAX_CONTAINER_PORTS, image_matches, image_repo, image_tag
from app.models import (
    MonitorCheck,
    MonitorDiscovery,
    MonitorFinding,
    MonitorModuleTombstone,
    MonitorState,
)
from app.rule_layer import convert, effective, merge, read_layer, store_layer
from app.template_sync import (
    TEMPLATE_CHECK_FIELDS,
    SchedulerAction,
    apply_scheduler_actions,
    read_overrides,
)

logger = logging.getLogger(__name__)

# The catalog's probe intervals in the notation of a check row.
_INTERVAL_TEXT = {300: "5m", 900: "15m", 3600: "1h", 86400: "24h"}
# Names no public resolver answers (RFC 6761, RFC 6762, RFC 8375, .internal) and .lan and
# .home by habit: a central check of them could only ever say "not public" (Kevin 2026-11-18).
_PRIVATE_SUFFIXES = (
    "localhost",
    "test",
    "example",
    "invalid",
    "local",
    "home.arpa",
    "internal",
    "lan",
    "home",
)


class AdoptError(Exception):
    """The finding cannot be adopted as it stands."""


@dataclass
class AdoptResult:
    finding: MonitorFinding
    enabled: list[str] = field(default_factory=list)  # check ids now alerting
    disabled: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"key", "reason"}
    updated: list[str] = field(default_factory=list)  # check ids given the new definition


def definition_hash(check: Check) -> str:
    """Hash of the catalog check as the catalog defines it. A check row keeps the hash it
    was bound from, so a changed definition shows apart from the admin's own edits."""
    canonical = json.dumps(
        check.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def updatable_checks(checks: list[MonitorCheck], module: Module | None) -> list[MonitorCheck]:
    """The checks whose catalog definition changed since they were bound. A row without a
    hash (bound before R-1264) is never offered: nothing shows what it was bound from, and
    neither is a row at another instance than the one its check now names (R-1528): it
    stays as it was, like a row the catalog dropped."""
    if module is None:
        return []
    by_key = {check.key: check for check in module.checks}
    hashes = {key: definition_hash(check) for key, check in by_key.items()}
    return [
        row
        for row in checks
        if row.module_check_hash is not None
        and row.module_check_key in hashes
        and row.module_check_hash != hashes[row.module_check_key]
        and by_key[row.module_check_key].instance in (None, row.module_instance)
    ]


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


def tombstoned_keys(db: Session, finding: MonitorFinding) -> set[str]:
    """Check keys of this instance the admin deleted: neither adopt nor the catalog
    sync creates them again."""
    rows = db.query(MonitorModuleTombstone.check_key).filter(
        MonitorModuleTombstone.server_id == finding.server_id,
        MonitorModuleTombstone.module_id == finding.module_id,
        MonitorModuleTombstone.instance_key == finding.instance_key,
    )
    return {key for (key,) in rows}


# The parts of a module check's config that _update carries over from the row: the
# admin may change them without making the definition their own.
_KEPT_ON_UPDATE = ("interval_s", "timeout_s", "pair_check_id")


def _own_config(config: str | None) -> dict | None:
    try:
        parsed = json.loads(config) if config else {}
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {k: v for k, v in parsed.items() if k not in _KEPT_ON_UPDATE}


def mark_module_overrides(
    check: MonitorCheck, *, enabled: bool | None = None, old_config: str | None = None
) -> None:
    """Record in overridden_fields what the admin made their own on a module check:
    switched it off ("enabled"), so a returning instance leaves it off (R-1573), or
    changed its rules ("config"), so a catalog update does not overwrite them (R-1567).
    Switching it on again drops the mark; changed rules stay the admin's. Template and
    manual checks are left to mark_overrides."""
    if check.module_id is None:
        return
    fields = read_overrides(check)
    if enabled is not None:
        if enabled:
            fields.discard("enabled")
        else:
            fields.add("enabled")
    if old_config is not None and _own_config(old_config) != _own_config(check.config):
        fields.add("config")
    check.overridden_fields = json.dumps([f for f in TEMPLATE_CHECK_FIELDS if f in fields])


def tombstone_module_check(db: Session, check: MonitorCheck) -> None:
    """Record a module check the admin is deleting. The key comes from the stored row
    only, so a request cannot bury a check it does not delete."""
    if not (check.module_id and check.module_instance and check.module_check_key):
        return
    known = (
        db.query(MonitorModuleTombstone)
        .filter(
            MonitorModuleTombstone.server_id == check.server_id,
            MonitorModuleTombstone.module_id == check.module_id,
            MonitorModuleTombstone.instance_key == check.module_instance,
            MonitorModuleTombstone.check_key == check.module_check_key,
        )
        .first()
    )
    if known is None:
        db.add(
            MonitorModuleTombstone(
                id=str(uuid.uuid4()),
                server_id=check.server_id,
                module_id=check.module_id,
                instance_key=check.module_instance,
                check_key=check.module_check_key,
            )
        )


def _summary(finding: MonitorFinding) -> dict:
    try:
        summary = json.loads(finding.summary)
    except (TypeError, ValueError):
        return {}
    return summary if isinstance(summary, dict) else {}


def _scan(db: Session, server_id: str) -> tuple[list[dict], list[dict] | None]:
    """(the containers, the listening sockets) of the host's last scan; the sockets are
    None when the scan did not see them whole (cut, an older agent, no scan yet)."""
    row = db.get(MonitorDiscovery, server_id)
    if row is None:
        return [], None
    inventory = json.loads(row.inventory)
    whole = inventory.get("complete", {}).get("sockets") is True
    return inventory.get("containers", []), inventory.get("sockets") if whole else None


def _target_name(
    module: Module,
    kind: str,
    service: str,
    key: str,
    summary: dict,
    containers: list[dict],
    image_fallback: bool = False,
) -> tuple[str | None, str | None]:
    """(the container, unit or process of the instance a check of this kind asks, None)
    or (None, why there is none). With `image_fallback` a missing service falls back to
    the instance's one container with the module's image whose service no other check
    names."""
    none = f"no {kind} for this instance"
    matched_by = summary.get("matched_by")
    if matched_by is not None:
        # Found outside its own kind of instance: only an unambiguous unit or process of
        # the match can be asked.
        names = [m.split(":", 1)[1] for m in matched_by if m.startswith(kind + ":")]
        return (names[0], None) if len(names) == 1 else (None, none)
    if kind == module.instance:
        # The key may differ from the name the agent asks by (MSSQL-SHOP for MSSQL$SHOP).
        return summary.get(kind, key), None
    if kind == "container" and module.instance == "compose_project":
        if "container" in summary:
            # A container of the module outside any project: it has no other services.
            if service and not image_fallback:
                return None, none
            return summary["container"], None
        # The name as the last scan saw it; the agent asks this container, and a new
        # name (a rebuilt project) is a changed finding.
        prefixes = [image_repo(p) for p in module.detect.container_images]
        project = [c for c in containers if c["compose_project"] == key]
        if service:
            names = sorted(c["name"] for c in project if c["compose_service"] == service)
            if not names and image_fallback:
                # Another check's service is that container's own job (Nextcloud's cron
                # runs the app image too), never the fallback.
                named = {
                    c.target.service
                    for c in module.checks
                    if c.target is not None and c.target.service != service
                }
                names = sorted(
                    c["name"]
                    for c in project
                    if c["compose_service"] not in named
                    and image_matches(image_repo(c["image"]), prefixes)
                )
        else:
            names = sorted(
                c["name"] for c in project if image_matches(image_repo(c["image"]), prefixes)
            )
        if len(names) > 1:
            # The check's target must be unambiguous; with several replicas none is picked.
            return None, f"several containers for this instance: {', '.join(names)}"
        return (names[0], None) if names else (None, none)
    return None, none


def _seen_ports(name: str, containers: list[dict]) -> tuple[set[int], bool]:
    """(the TCP ports the last scan saw at the container, whether they are the listening
    ones): those listening in its network if the scan saw them, else the exposed ones (the
    docservice of the OnlyOffice image listens on 8000, the image exposes 80 and 443).
    A full exposed list counts as none seen."""
    for c in containers:
        if c["name"] == name:
            listening = c.get("listening")
            if listening is not None:
                return set(listening), True
            if len(c["ports"]) >= MAX_CONTAINER_PORTS:
                # Agent and server cut the list there (lowest ports first): a port beyond
                # the cut would pass for missing.
                return set(), False
            return {p["private"] for p in c["ports"] if p["proto"] == "tcp"}, False
    return set(), False


def _lacks_port(name: str, port: int, containers: list[dict]) -> bool:
    """Whether the last scan saw the container with TCP ports, the hint not among them."""
    ports, _ = _seen_ports(name, containers)
    return bool(ports) and port not in ports


def _tag_mismatch(name: str, check: Check, containers: list[dict]) -> str | None:
    """Why the container's image tag does not fit the check's tags, None when it does."""
    tags = ", ".join(check.image_tags or [])
    for c in containers:
        if c["name"] == name:
            tag = image_tag(c["image"])
            if any(fnmatch.fnmatchcase(tag, p) for p in check.image_tags or []):
                return None
            return f"container {name} runs the tag {tag or '(unknown)'}, the check needs {tags}"
    return f"no tag known for container {name}, the check needs {tags}"


def _alternative(
    name: str, alternatives: list[Alternative], containers: list[dict]
) -> tuple[Alternative | None, str | None]:
    """(the first alternative whose port the last scan saw at the container, None) or
    (None, why none is picked). Without seen ports (stopped, host network) the first."""
    ports, listening = _seen_ports(name, containers)
    if not ports:
        return alternatives[0], None
    seen = [a for a in alternatives if a.port_hint in ports]
    hints = ", ".join(str(a.port_hint) for a in alternatives)
    if not seen:
        return None, f"container {name} has none of the ports {hints}"
    if len(seen) > 1 and not listening:
        # An image exposes its TLS port whether TLS is on or not; only the listening
        # ports tell, and a guess would alert on a port nothing listens on.
        return None, f"container {name} exposes several of the ports {hints}, none seen listening"
    return seen[0], None


def _host_alternative(
    kind: str, name: str, alternatives: list[Alternative], sockets: list[dict] | None
) -> tuple[Alternative | None, str | None]:
    """(the first alternative whose port the last scan saw listening at the host, None) or
    (None, why none is picked): for a unit target the sockets of its processes, for a
    loopback one those outside any container. Without the sockets (cut, an agent that
    does not tell the unit) the first: the agent asks it."""
    if kind == "unit":
        if sockets is None or not any(s["unit"] for s in sockets):
            return alternatives[0], None
        ports = {s["port"] for s in sockets if s["unit"] == name and s["proto"].startswith("tcp")}
        where = f"unit {name}"
    else:
        if sockets is None:
            return alternatives[0], None
        ports = {s["port"] for s in sockets if not s["container"] and s["proto"].startswith("tcp")}
        where = "the host"
    for alternative in alternatives:
        if alternative.port_hint in ports:
            return alternative, None
    hints = ", ".join(str(a.port_hint) for a in alternatives)
    return None, f"{where} listens on none of the ports {hints}"


def probe_config(
    module: Module,
    check: Check,
    key: str,
    summary: dict,
    containers: list[dict],
    sockets: list[dict] | None = None,
) -> tuple[dict | None, str | None]:
    """(the probe config of the catalog check bound to the instance, None) or
    (None, why it cannot be bound)."""
    target = None
    if check.target is not None:
        t = check.target
        name = ""
        port_hint, scheme = t.port_hint, t.scheme
        if t.kind == "port":
            if port_hint is None:
                port_hint = summary.get("port")
            if port_hint is None:
                return None, "no port for this instance"
        elif t.kind == "vhost":
            # The vhost's own port: the agent finds the vhost again by its name and port.
            name, port_hint = key, summary.get("port")
            if port_hint is None:
                return None, "no port for this vhost"
            # The agent asks a vhost by its name and cannot tell its scheme by a handshake
            # (sensor_http.go): the scheme of an HTTP check comes from the vhost's TLS.
            if scheme is None and check.sensor == "http":
                scheme = "https" if summary.get("tls") else "http"
        elif t.kind != "loopback":
            name, why = _target_name(
                module, t.kind, t.service, key, summary, containers, t.image_fallback
            )
            if not name:
                return None, why
            # The agent asks a container's only port when the hint does not listen (target.go
            # pickPort): an HTTP check of Nextcloud's apache image would ask the FastCGI port
            # of its fpm image and alert. Without seen ports (stopped, host network) the agent
            # decides.
            if t.kind == "container" and port_hint and _lacks_port(name, port_hint, containers):
                return None, f"container {name} has no port {port_hint}"
            if check.image_tags:
                why = _tag_mismatch(name, check, containers)
                if why:
                    return None, why
            if t.alternatives and t.kind == "container":
                picked, why = _alternative(name, t.alternatives, containers)
                if picked is None:
                    return None, why
                port_hint, scheme = picked.port_hint, picked.scheme
        if t.alternatives and t.kind in ("loopback", "unit"):
            picked, why = _host_alternative(t.kind, name, t.alternatives, sockets)
            if picked is None:
                return None, why
            port_hint, scheme = picked.port_hint, picked.scheme
        target = {"kind": t.kind, "name": name, "port_hint": port_hint, "scheme": scheme}
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
        else {
            "ref": f"{module.id}/{key}/{check.credential.slot}",
            "use": check.credential.use,
            **({"optional": True} if check.credential.optional else {}),
        },
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


def _public_name(name: str) -> bool:
    name = name.lower().rstrip(".")
    # A single label resolves through the host's search domain, never publicly (R-1548).
    if "." not in name:
        return False
    return not any(name == s or name.endswith("." + s) for s in _PRIVATE_SUFFIXES)


def central_config(check: Check, key: str, summary: dict) -> tuple[dict | None, str | None]:
    """(the central config of the catalog check bound to the vhost named key, None) or
    (None, why it cannot be bound)."""
    if not _public_name(key):
        return None, "not a public name"
    config: dict = {"sensor": check.sensor, "host": key, "params": dict(check.params)}
    if CENTRAL_SENSORS[check.sensor].default_port is not None:
        # From outside on the port the vhost listens on, like the agent's own check.
        if summary.get("port") is None:
            return None, "no port for this vhost"
        config["port"] = summary["port"]
    try:
        CentralConfig.model_validate(config)
    except ValueError as exc:
        logger.warning("Catalog check %s does not bind to %s: %s", check.key, key, exc)
        return None, "the bound check does not hold"
    return config, None


def _bound_config(
    module: Module,
    check: Check,
    key: str,
    summary: dict,
    containers: list[dict],
    sockets: list[dict] | None,
) -> tuple[dict | None, str | None]:
    if check.central:
        return central_config(check, key, summary)
    return probe_config(module, check, key, summary, containers, sockets)


def _belongs(check: Check, finding: MonitorFinding) -> bool:
    """Whether the check is bound at the finding's instance: a check that names one
    instance (R-1528) at that one only, the others skip it without a reason."""
    return check.instance is None or check.instance == finding.instance_key


def _create(
    db: Session,
    finding: MonitorFinding,
    module: Module,
    check: Check,
    summary: dict,
    containers: list[dict],
    sockets: list[dict] | None,
    *,
    silent: bool,
) -> tuple[MonitorCheck | None, str | None]:
    config, reason = _bound_config(
        module, check, finding.instance_key, summary, containers, sockets
    )
    if config is None:
        return None, reason
    row = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id=finding.server_id,
        name=f"{module.name} ({finding.instance_key}): {check.name}",
        check_type="central" if check.central else "probe",
        config=json.dumps(config),
        enabled=True,
        interval=_INTERVAL_TEXT[check.interval],
        module_id=module.id,
        module_instance=finding.instance_key,
        module_check_key=check.key,
        module_check_hash=definition_hash(check),
        silent=silent,
    )
    if not check.central:
        store_layer(row, config["rules"], {})
    db.add(row)
    db.add(MonitorState(check_id=row.id, status="pending"))
    return row, None


def _update(
    row: MonitorCheck,
    module: Module,
    check: Check,
    key: str,
    summary: dict,
    containers: list[dict],
    sockets: list[dict] | None,
    now: datetime,
) -> str | None:
    """Give the row the catalog's new definition; why not, or None. The admin's interval
    and timeout stay (the only parts of a probe config besides rules the admin can edit,
    routers/checks.py), as do the row's name and switches; a central row keeps its
    interval and the partner the admin gave it. A probe row's rule overrides go over the
    new catalog rules (merge), the conflicts of this merge into its layer and the log; one
    whose rules the admin changed before the layer keeps them (R-1638)."""
    layer = read_layer(row)
    if layer is None and "config" in read_overrides(row):
        return "the admin changed the check's rules; they stay"
    if (row.check_type == "central") != check.central:
        return "the catalog moved the check between the agent and the monitoring service"
    config, reason = _bound_config(module, check, key, summary, containers, sockets)
    if config is None:
        return reason
    try:
        old = json.loads(row.config)
    except (TypeError, ValueError):
        old = {}
    if isinstance(old, dict):
        for part in ("pair_check_id",) if check.central else ("interval_s", "timeout_s"):
            if part in old:
                config[part] = old[part]
    try:
        if check.central:
            CentralConfig.model_validate(config)
        else:
            catalog = config["rules"]
            overrides, conflicts = (
                ({}, []) if layer is None else merge(layer["catalog"], catalog, layer["overrides"])
            )
            ProbeConfig.model_validate({**config, "rules": effective(catalog, overrides)})
    except ValueError:
        return "the updated check does not hold"
    row.config = json.dumps(config)
    row.module_check_hash = definition_hash(check)
    if not check.central:
        at = now.isoformat()
        store_layer(row, catalog, overrides, [{**c, "at": at} for c in conflicts])
        for c in conflicts:
            logger.warning(
                "Module check %s: the catalog update meets the admin's rule %s (%s)",
                row.id,
                c["key"],
                c["kind"],
            )
    return None


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
        tagged = {check.key for check in module.checks if check.image_tags}
        summary = _summary(finding)
        fitting = summary.get("tag_checks")
        containers, sockets = _scan(db, finding.server_id)
        by_key = {check.key: check for check in module.checks}
        updatable = {row.id for row in updatable_checks(checks, module)}
        kept: list[MonitorCheck] = []
        for row in checks:
            if row.module_check_key not in keys:
                kept.append(row)
                continue  # dropped from the catalog: stays as the admin left it
            if by_key[row.module_check_key].instance not in (None, finding.instance_key):
                kept.append(row)
                continue  # the check names another instance now: stays as it is
            if row.module_check_key in tagged and fitting is not None:
                if row.module_check_key not in fitting:
                    # The image moved to a tag the check does not fit (Wiki.js 2 -> 3). Deleted
                    # without a tombstone, not switched off: a switched-off row looks like the
                    # admin's own choice, and only a missing one is created again on the way back.
                    if row.enabled:
                        result.disabled.append(row.id)
                        actions.append(("remove", row.id, None, None))
                    db.delete(row)
                    continue
            kept.append(row)
            if row.id in updatable:
                key = row.module_check_key
                why = _update(
                    row,
                    module,
                    by_key[key],
                    finding.instance_key,
                    summary,
                    containers,
                    sockets,
                    now,
                )
                if why is None:
                    result.updated.append(row.id)
                else:
                    # The old definition keeps running; the admin sees why.
                    result.skipped.append({"key": key, "reason": why})
            # A new instance is watched whole again (adopting "gone" switched its checks
            # off), except the checks the admin switched off; on a changed one, those stay
            # off too.
            if finding.kind == "new" and "enabled" not in read_overrides(row):
                row.enabled = True
            row.silent = False
            if row.enabled:
                result.enabled.append(row.id)
                actions.append(("add", row.id, row.interval, row.check_type))
        have = {row.module_check_key for row in kept} | tombstoned_keys(db, finding)
        for check in module.checks:
            if check.key in have or not _belongs(check, finding):
                continue
            row, reason = _create(
                db, finding, module, check, summary, containers, sockets, silent=False
            )
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


def _stored_rules(row: MonitorCheck) -> tuple[list[dict] | None, str | None]:
    try:
        rules = [Rule.model_validate(rule) for rule in json.loads(row.config)["rules"]]
    except (TypeError, ValueError, KeyError):
        return None, "its rules cannot be read"
    problems = rule_problems(rules)
    if problems:
        return None, problems[0]
    return [rule.model_dump() for rule in rules], None


def _conversion(
    row: MonitorCheck, rules: list[dict], catalog: Catalog
) -> tuple[tuple[list[dict], dict] | None, str | None]:
    """((the catalog rules, the overrides), None) for a check whose rules the admin changed
    before the layer, or (None, why it stays frozen)."""
    module = catalog.modules.get(row.module_id)
    check = None
    if module is not None:
        check = next((c for c in module.checks if c.key == row.module_check_key), None)
    if check is None:
        return None, "the catalog has no such check"
    if row.module_check_hash != definition_hash(check):
        # Also when the catalog moved the check to the monitoring service. Without a hash
        # nothing shows the definition the rules were changed from.
        return None, "it is bound to another definition than today's"
    bound = [rule.model_dump() for rule in check.rules]
    overrides, why = convert(bound, rules)
    if overrides is None:
        return None, why
    return (bound, overrides), None


def record_rule_layers(db: Session, *, catalog: Catalog | None = None) -> tuple[int, int, int]:
    """Give the probe checks of modules without a rule layer one (R-1638); returns how many
    it recorded, converted and left frozen. Runs at start-up before sync_catalog, which
    gives a check without a hash today's; a check left frozen is looked at again each start.

    A check whose rules are the catalog's (no mark "config") takes its stored rules as the
    catalog state it is bound to, also with an update pending. One whose rules the admin
    changed becomes catalog and overrides only when it is bound to today's definition and
    they give its rules exactly (converted); else it stays as it is, and no update touches
    its rules."""
    catalog = catalog or get_catalog()
    rows = (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.module_id.isnot(None),
            MonitorCheck.check_type == "probe",
            MonitorCheck.rule_layer.is_(None),
        )
        .order_by(MonitorCheck.id)
        .all()
    )
    recorded = converted = frozen = 0
    for row in rows:
        rules, why = _stored_rules(row)
        if "config" not in read_overrides(row):
            if rules is None:
                logger.warning("Module check %s keeps no rule layer: %s", row.id, why)
                continue
            store_layer(row, rules, {})
            recorded += 1
            continue
        layer = None
        if rules is not None:
            layer, why = _conversion(row, rules, catalog)
        if layer is None:
            logger.debug("Module check %s keeps the admin's rules frozen: %s", row.id, why)
            frozen += 1
            continue
        store_layer(row, *layer)
        converted += 1
    db.commit()
    if recorded or converted or frozen:
        logger.info(
            "Rule layers: %d recorded, %d converted, %d frozen (the admin's rules stay)",
            recorded,
            converted,
            frozen,
        )
    return recorded, converted, frozen


def sync_catalog(db: Session, *, catalog: Catalog | None = None) -> int:
    """Bring adopted instances up to a changed catalog; returns how many findings it
    reopened. Runs at start-up before load_all_checks, which schedules what it adds.

    A check the catalog added is created silent; a check it dropped stays; an active
    check whose definition changed keeps running as it is. Each makes the finding
    "changed" and open, so the admin sees it and adopting makes the new checks alert and
    writes the new definitions. A check the admin deleted is not created again. A module
    the catalog no longer has is left alone. A check bound before definitions had a hash
    gets today's, without an update: nothing shows what it was bound from. One whose rules
    the admin changed and that has no rule layer gets none, so record_rule_layers does not
    take its rules for changed from today's definition at a later start."""
    catalog = catalog or get_catalog()
    reopened = 0
    unhashed = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.module_id.isnot(None), MonitorCheck.module_check_hash.is_(None))
        .all()
    )
    for row in unhashed:
        if row.rule_layer is None and "config" in read_overrides(row):
            continue
        module = catalog.modules.get(row.module_id)
        check = None
        if module is not None:
            check = next((c for c in module.checks if c.key == row.module_check_key), None)
        if check is not None:
            row.module_check_hash = definition_hash(check)
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
        have = {row.module_check_key for row in checks} | tombstoned_keys(db, finding)
        keys = {check.key for check in module.checks}
        dropped = any(row.enabled and row.module_check_key not in keys for row in checks)
        changed = any(row.enabled for row in updatable_checks(checks, module))
        summary = _summary(finding)
        containers, sockets = _scan(db, finding.server_id)
        created = False
        for check in module.checks:
            if check.key in have or not _belongs(check, finding):
                continue
            row, _ = _create(db, finding, module, check, summary, containers, sockets, silent=True)
            created = created or row is not None
        if created or dropped or changed:
            finding.kind, finding.status, finding.decided_at = "changed", "open", None
            reopened += 1
        finding.catalog_version = catalog.version
    db.commit()
    if reopened:
        logger.info("Catalog update: %d adopted module instance(s) changed", reopened)
    return reopened
