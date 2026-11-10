# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Module discovery (R-1223): what the agent found on its host, when it looks again, and
which catalog modules that makes into the findings inbox.

The agent reports a discovery block only in the run in which it scanned. The block is
cut to the contract (names, ports, states; never config contents, command lines or
environment) and stored; then every catalog module is matched against it. Each instance
of a module (a compose project, a container, a unit, a process, a port) becomes one
finding, keyed by a name the agent reported, so the same instance keeps its finding
from scan to scan.

Nothing here deletes a check. An instance that disappears becomes a finding "gone" only
after two full scans without it, so a partial scan (the agent ran out of time) and a
service restarting during one scan make nothing disappear.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import random
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from itertools import islice

from sqlalchemy.orm import Session

from app.catalog.loader import Catalog, get_catalog
from app.catalog.model import Module
from app.check_configs import CREDENTIAL_REF_MAX, CREDENTIAL_REF_PATTERN
from app.checkers.agent import agent_number
from app.core.time import utcnow_naive
from app.models import MonitorCheck, MonitorDiscovery, MonitorFinding

logger = logging.getLogger(__name__)

# The bounds of the report contract (spec "Report-Blöcke"); a longer list is cut, and a
# cut scan counts as partial: what fell off must not look gone.
MAX_UNITS = 1000
MAX_SOCKETS = 1000
MAX_CONTAINERS = 500
MAX_MARKERS = 1000
MAX_PORTS = 1000
MAX_CONTAINER_PORTS = 64
MAX_MOUNTS = 32
MAX_CREDENTIALS = 256

SCAN_AFTER_MIN = timedelta(hours=24)
SCAN_AFTER_MAX = timedelta(hours=48)

# Never a port finding, whatever the agent sent: probing these on a cycle locks the admin
# out (OpenSSH penalties, MySQL max_connect_errors) or prints the probe (raw printing
# 9100-9107). The agent skips them already; this is the second line.
_NEVER_PORTS = frozenset({22, 3306, *range(9100, 9108)})
_NEVER_PROCESSES = frozenset({"sshd", "mysqld", "mariadbd"})

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MARKER_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}")
_PROTOCOL = re.compile(r"[a-z0-9][a-z0-9_+.-]{0,31}")
# An instance key becomes a segment of a credential reference <module>/<instance>/<slot>
# (check_configs.ProbeCredential, at most 255 characters), so it has to fit one.
_INSTANCE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,119}")
_TCP = ("tcp", "tcp6")


# --- the inventory, cut to the contract -------------------------------------------------


def _text(value: object, limit: int) -> str:
    """A name of the contract; anything else, too long or with control characters, is ""
    (a cut name would be another name)."""
    if not isinstance(value, str) or len(value) > limit or _CONTROL.search(value):
        return ""
    return value


def _port(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        return None
    return value


def _cleaned(
    raw: object, clean: Callable[[object], object | None], limit: int
) -> tuple[list, bool]:
    """(the entries `clean` accepts among the first `limit`, whether the list was longer)."""
    if not isinstance(raw, list):
        return [], False
    kept = [entry for entry in map(clean, raw[:limit]) if entry is not None]
    return kept, len(raw) > limit


def _unit(raw: object) -> dict | None:
    if not isinstance(raw, dict) or not (name := _text(raw.get("name"), 255)):
        return None
    return {"name": name, "state": _text(raw.get("state"), 64), "sub": _text(raw.get("sub"), 64)}


def _socket(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    port, proto = _port(raw.get("port")), _text(raw.get("proto"), 8)
    if port is None or not proto:
        return None
    return {
        "proto": proto,
        "addr": _text(raw.get("addr"), 64),
        "port": port,
        "process": _text(raw.get("process"), 255),
        "container": _text(raw.get("container"), 255),
    }


def _container_port(raw: object) -> dict | None:
    if not isinstance(raw, dict) or (private := _port(raw.get("private"))) is None:
        return None
    return {
        "private": private,
        "public": _port(raw.get("public")),
        "proto": _text(raw.get("proto"), 8),
    }


def _container(raw: object) -> dict | None:
    if not isinstance(raw, dict) or not (name := _text(raw.get("name"), 255)):
        return None
    ports, _ = _cleaned(raw.get("ports"), _container_port, MAX_CONTAINER_PORTS)
    mounts, _ = _cleaned(raw.get("mounts"), lambda m: _text(m, 1024) or None, MAX_MOUNTS)
    return {
        "id": _text(raw.get("id"), 128),
        "name": name,
        "image": _text(raw.get("image"), 512),
        "compose_project": _text(raw.get("compose_project"), 255),
        "compose_service": _text(raw.get("compose_service"), 255),
        "state": _text(raw.get("state"), 64),
        "health": _text(raw.get("health"), 64),
        "ports": ports,
        "mounts": mounts,
    }


def _recognised_port(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    port, proto = _port(raw.get("port")), _text(raw.get("proto"), 8)
    protocol = raw.get("protocol")
    if port is None or not proto or not isinstance(protocol, str):
        return None
    if not _PROTOCOL.fullmatch(protocol):
        return None
    return {"port": port, "proto": proto, "protocol": protocol}


def clean_inventory(block: object) -> dict | None:
    """The discovery block cut to the contract; None if it is no object. Entries that
    break the contract are dropped one by one, fields outside it are never kept."""
    if not isinstance(block, dict):
        return None
    units, cut_units = _cleaned(block.get("units"), _unit, MAX_UNITS)
    sockets, cut_sockets = _cleaned(block.get("sockets"), _socket, MAX_SOCKETS)
    containers, cut_containers = _cleaned(block.get("containers"), _container, MAX_CONTAINERS)
    ports, cut_ports = _cleaned(block.get("ports"), _recognised_port, MAX_PORTS)
    raw_markers = block.get("markers")
    raw_markers = raw_markers if isinstance(raw_markers, dict) else {}
    markers = {
        key: value
        for key, value in islice(raw_markers.items(), MAX_MARKERS)
        if isinstance(key, str) and _MARKER_ID.fullmatch(key) and isinstance(value, bool)
    }
    cut = cut_units or cut_sockets or cut_containers or cut_ports or len(raw_markers) > MAX_MARKERS
    duration = agent_number(block.get("duration_ms"))
    return {
        "ts": agent_number(block.get("ts")),
        "duration_ms": duration if duration is not None and duration >= 0 else None,
        "partial": block.get("partial") is True or cut,
        "units": units,
        "sockets": sockets,
        "containers": containers,
        "markers": markers,
        "ports": ports,
    }


# --- when the agent looks again ---------------------------------------------------------


def next_scan_at(now: datetime, rng: random.Random | None = None) -> datetime:
    """24 to 48 h after `now`, at random: the hosts of one install do not all scan at once."""
    spread = (SCAN_AFTER_MAX - SCAN_AFTER_MIN).total_seconds()
    return now + SCAN_AFTER_MIN + timedelta(seconds=(rng or random).uniform(0, spread))


def scan_due(row: MonitorDiscovery | None, now: datetime) -> bool:
    """Whether the next plan asks the agent for a discovery: at once for a host never
    scanned, when the admin asked for it, else once `next_scan_at` has passed."""
    if row is None or row.scanned_at is None or row.scan_requested_at is not None:
        return True
    return row.next_scan_at is None or row.next_scan_at <= now


# --- matching the inventory against the catalog -----------------------------------------


def image_repo(image: str) -> str:
    """The repository of an image reference without tag or digest, Docker Hub images in
    their short form: `docker.io/library/postgres:16` and `postgres` are the same."""
    repo = image.split("@", 1)[0]
    if repo.rfind(":") > repo.rfind("/"):
        repo = repo[: repo.rfind(":")]
    repo = repo.lower()
    for hub in ("docker.io/", "index.docker.io/"):
        if repo.startswith(hub):
            repo = repo[len(hub) :]
            break
    return repo.removeprefix("library/")


def image_matches(repo: str, prefixes: list[str]) -> bool:
    # A prefix ends at a path boundary: ghcr.io/immich-app takes ghcr.io/immich-app/x,
    # paperless-ngx does not take paperless-ngx-fork.
    return any(repo == p or repo.startswith(p + "/") for p in prefixes)


def _unit_name(name: str) -> str:
    return name if "." in name else name + ".service"


def _instances(module: Module, inv: dict) -> tuple[dict[str, dict], list[dict], set[str]]:
    """(instance key → summary, the containers and processes the module claims)."""
    detect = module.detect
    prefixes = [image_repo(p) for p in detect.container_images]
    containers = [
        c for c in inv["containers"] if prefixes and image_matches(image_repo(c["image"]), prefixes)
    ]
    wanted_units = {_unit_name(u) for u in detect.units}
    # An installed but stopped unit is not in use; a failed one is, and must stay watched.
    units = sorted(
        {u["name"] for u in inv["units"] if u["name"] in wanted_units and u["state"] != "inactive"}
    )
    wanted_processes = set(detect.processes)
    processes = sorted({s["process"] for s in inv["sockets"] if s["process"] in wanted_processes})
    markers = sorted(m.id for m in detect.markers if inv["markers"].get(m.id) is True)

    found: dict[str, dict] = {}
    if module.instance == "compose_project":
        for c in containers:
            project = c["compose_project"]
            if project:
                # Every service of the project, not only the matched one: a check may ask
                # another service of the instance (target.service).
                services = {
                    o["compose_service"]: image_repo(o["image"])
                    for o in inv["containers"]
                    if o["compose_project"] == project
                }
                found[project] = {"services": dict(sorted(services.items()))}
            else:
                found[c["name"]] = {"container": c["name"], "image": image_repo(c["image"])}
    elif module.instance == "container":
        for c in containers:
            found[c["name"]] = {
                "image": image_repo(c["image"]),
                "project": c["compose_project"],
                "service": c["compose_service"],
            }
    elif module.instance == "unit":
        found = {name: {"unit": name} for name in units}
    elif module.instance == "process":
        found = {name: {"process": name} for name in processes}
    matched_by = (
        [f"image:{r}" for r in sorted({image_repo(c["image"]) for c in containers})]
        + [f"unit:{u}" for u in units]
        + [f"process:{p}" for p in processes]
        + [f"marker:{m}" for m in markers]
    )
    if not found and matched_by:
        # Installed, but not in the module's own kind of instance (a package instead of a
        # container): one instance named after the module.
        found = {module.id: {"matched_by": matched_by}}
    # A name that cannot be part of a reference makes no instance (and no stand-in).
    found = {key: summary for key, summary in found.items() if _INSTANCE_KEY.fullmatch(key)}
    return found, containers, set(processes)


def _beyond_loopback(addr: str) -> bool:
    host = addr.strip("[]").split("%", 1)[0]
    if host == "*":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # no address the agent gave: not offered
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_loopback


def _port_instances(
    inv: dict, claimed_containers: set[str], claimed_processes: set[str], claimed_ports: set[int]
) -> dict[str, dict]:
    """A finding per TCP port the agent recognised a protocol on, that listens beyond
    loopback and that no found module claims."""
    found: dict[str, dict] = {}
    for entry in inv["ports"]:
        port = entry["port"]
        if entry["proto"] not in _TCP or port in _NEVER_PORTS or port in claimed_ports:
            continue
        sockets = sorted(
            (
                s
                for s in inv["sockets"]
                if s["port"] == port and s["proto"] in _TCP and _beyond_loopback(s["addr"])
            ),
            key=lambda s: (s["process"], s["container"]),
        )
        if not sockets or any(
            s["process"] in _NEVER_PROCESSES
            or s["process"] in claimed_processes
            or (s["container"] and s["container"] in claimed_containers)
            for s in sockets
        ):
            continue
        found[f"tcp-{port}"] = {
            "port": port,
            "proto": "tcp",
            "protocol": entry["protocol"],
            "process": sockets[0]["process"],
            "container": sockets[0]["container"],
        }
    return found


def match_inventory(inv: dict, catalog: Catalog) -> dict[tuple[str, str], dict]:
    """(module id, instance key) → summary of every module instance in the inventory.

    The summary holds only what makes the instance what it is (names, images, the
    recognised protocol), never a state; a different summary is a finding "changed".
    """
    seen: dict[tuple[str, str], dict] = {}
    claimed_containers: set[str] = set()
    claimed_processes: set[str] = set()
    claimed_ports: set[int] = set()
    port_modules = []
    for module in catalog.modules.values():
        if module.instance == "port":
            port_modules.append(module)
            continue
        found, containers, processes = _instances(module, inv)
        if not found:
            continue
        seen.update({(module.id, key): summary for key, summary in found.items()})
        claimed_containers.update(c["name"] for c in containers)
        claimed_ports.update(p["public"] for c in containers for p in c["ports"] if p["public"])
        claimed_processes.update(processes)
        claimed_ports.update(module.detect.port_hints)
    for module in port_modules:
        found = _port_instances(inv, claimed_containers, claimed_processes, claimed_ports)
        seen.update({(module.id, key): summary for key, summary in found.items()})
    return seen


# --- the findings inbox -----------------------------------------------------------------


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _summary(row: MonitorFinding) -> object:
    try:
        return json.loads(row.summary)
    except (TypeError, ValueError):
        return None


def _seen_again(row: MonitorFinding, summary: dict, watched: bool, in_step: bool) -> None:
    same = _summary(row) == summary
    before = (row.kind, row.status)
    if row.kind == "gone":
        if row.status != "adopted" and watched and same and in_step:
            # Back before the admin acted on it, its checks still on: as before. Not when
            # the catalog changed meanwhile: the start-up sync skips an open finding, so
            # only adopting it adds the new checks (and lets a silent one alert).
            row.kind, row.status = "new", "adopted"
        elif row.status != "adopted" and watched:
            row.kind, row.status = "changed", "open"
        else:
            # Adopting "gone" switched its checks off; adopting it again switches them on.
            row.kind, row.status = "new", "open"
    elif row.status != "open" and not same:
        # A dismissed finding stays dismissed until it changes; an adopted one that
        # changed is a finding "changed".
        if row.status == "adopted":
            row.kind = "changed"
        row.status = "open"
    if (row.kind, row.status) != before and row.status == "open":
        row.decided_at = None
    if not same or (row.kind, row.status) != before:
        row.summary = _dump(summary)


def _update_findings(
    db: Session,
    server_id: str,
    seen: dict[tuple[str, str], dict],
    catalog: Catalog,
    now: datetime,
    full_scan: bool,
    previous_full_scan: datetime | None,
) -> None:
    rows = {
        (row.module_id, row.instance_key): row
        for row in db.query(MonitorFinding).filter(MonitorFinding.server_id == server_id)
    }
    watched: set[tuple[str, str]] = set()
    silent: set[tuple[str, str]] = set()
    for module_id, instance, enabled, is_silent in db.query(
        MonitorCheck.module_id,
        MonitorCheck.module_instance,
        MonitorCheck.enabled,
        MonitorCheck.silent,
    ).filter(MonitorCheck.server_id == server_id, MonitorCheck.module_id.isnot(None)):
        if enabled:
            watched.add((module_id, instance))
        if is_silent:
            silent.add((module_id, instance))
    for key, summary in seen.items():
        row = rows.get(key)
        if row is None:
            db.add(
                MonitorFinding(
                    id=str(uuid.uuid4()),
                    server_id=server_id,
                    module_id=key[0],
                    instance_key=key[1],
                    kind="new",
                    status="open",
                    summary=_dump(summary),
                    catalog_version=catalog.version,
                    first_seen=now,
                    last_seen=now,
                )
            )
            continue
        row.last_seen = now
        # Only creating, adopting and the start-up sync set catalog_version: it names the
        # catalog the instance's checks were brought up to.
        in_step = row.catalog_version == catalog.version and key not in silent
        _seen_again(row, summary, key in watched, in_step)

    if not full_scan or previous_full_scan is None:
        return
    for key, row in rows.items():
        if key in seen or row.kind == "gone" or row.module_id not in catalog.modules:
            continue
        if row.last_seen >= previous_full_scan:
            continue  # seen in or after the previous full scan: one miss is no loss yet
        if key in watched:
            row.kind, row.status, row.decided_at = "gone", "open", None
        else:
            # Nothing watches it, so there is nothing to switch off: the entry is moot.
            db.delete(row)


def _full_scan_at(inventory: str | None) -> datetime | None:
    try:
        stamp = json.loads(inventory or "{}").get("full_scan_at")
        return datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    except (AttributeError, ValueError):
        return None


def apply_discovery(
    db: Session,
    server_id: str,
    block: object,
    *,
    catalog: Catalog | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> bool:
    """Store a discovery block of a report, plan the next scan and update the server's
    findings. Own commit; a failure is rolled back and only logged, it must never cost
    the report. Returns whether the block was stored."""
    inventory = clean_inventory(block)
    if inventory is None:
        return False
    catalog = catalog or get_catalog()
    now = now or utcnow_naive()
    try:
        row = db.get(MonitorDiscovery, server_id)
        if row is None:
            row = MonitorDiscovery(server_id=server_id)
            db.add(row)
        previous_full_scan = _full_scan_at(row.inventory)
        full_scan = not inventory["partial"]
        last_full = now if full_scan else previous_full_scan
        inventory["full_scan_at"] = last_full.isoformat() if last_full else None
        row.inventory = _dump(inventory)
        row.scanned_at = now
        row.next_scan_at = next_scan_at(now, rng)
        # A "scan now" pressed while this scan ran is answered by it too.
        row.scan_requested_at = None
        row.updated_at = now
        seen = match_inventory(inventory, catalog)
        _update_findings(db, server_id, seen, catalog, now, full_scan, previous_full_scan)
        db.commit()
    except Exception as exc:
        db.rollback()
        # No traceback: an agent can trigger this on every scan.
        logger.error("Storing the discovery failed (%s): %s", server_id, type(exc).__name__)
        return False
    return True


_CREDENTIAL_REF = re.compile(CREDENTIAL_REF_PATTERN)


def clean_credentials(block: object) -> dict[str, bool] | None:
    """The credential references the agent holds, as {ref: true}; never a value or hash.
    None for a block that is no object."""
    if not isinstance(block, dict):
        return None
    refs = sorted(
        ref
        for ref, present in islice(block.items(), MAX_CREDENTIALS)
        if present is True
        and isinstance(ref, str)
        and len(ref) <= CREDENTIAL_REF_MAX
        and _CREDENTIAL_REF.fullmatch(ref)
    )
    return dict.fromkeys(refs, True)


def apply_credentials(
    db: Session, server_id: str, block: object, *, now: datetime | None = None
) -> bool:
    """Replace the server's stored credential references with the report's. Own commit;
    a failure is rolled back and only logged. Returns whether the block was stored."""
    refs = clean_credentials(block)
    if refs is None:
        return False
    try:
        row = db.get(MonitorDiscovery, server_id)
        if row is None:
            row = MonitorDiscovery(server_id=server_id)
            db.add(row)
        row.credentials = _dump(refs)
        row.updated_at = now or utcnow_naive()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "Storing the credential references failed (%s): %s", server_id, type(exc).__name__
        )
        return False
    return True
