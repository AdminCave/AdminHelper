# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The policy file of frps' plugin (apps/agent/internal/frpspolicy): for each host the
SHA-256 of its key (proxy_key.py) and the proxies its frpc.toml carries, with the fields
frps hands the plugin for a new proxy (allowUsers as written, secretKey as its SHA-256).
The plugin admits only those.

The proxies come from the text generate_frpc_toml writes for the host, read back as TOML:
the same tunnels (active_tunnels), the same fields and the same allow users
(get_allow_users), so the policy cannot drift from what the agent runs. The server writes
the file after each change of tunnels, the FRP config, servers or users' access, at
startup, and every SYNC_INTERVAL seconds; frps checks a proxy only when it
registers, so a write changes nothing for proxies already up.

A custom domain that proxies of several servers carry without one non-empty group they all
share is left out for all of them (domain_conflicts): frps hands such a domain to whichever
proxy registers first. The tunnel API refuses to store a new one."""

import asyncio
import hashlib
import json
import logging
import tomllib
from collections import defaultdict

from sqlalchemy.orm import Session

from app.core import database
from app.modules.frp._helpers import get_allow_users, get_frp_config
from app.modules.frp.config_generator import _first_warning, generate_frpc_toml
from app.modules.frp.docker_manager import write_frps_policy
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.proxy_key import proxy_key_hash

logger = logging.getLogger(__name__)

# The format the plugin reads (frpspolicy.Version).
POLICY_VERSION = 2
# The types the plugin takes (frpspolicy.Parse); an entry of another type would make it
# refuse the whole file, and so every host.
_TYPES = ("stcp", "https")
# Seconds between two syncs of keep_policy_current; read at each round.
SYNC_INTERVAL = 60


def _flat(table: dict, prefix: str = "") -> dict:
    """The fields of a proxy table by their dotted key in lower case: frp reads the fields
    of a proxy without regard to case, and the API refuses keys that clash that way
    (_check_tunnel_extra_config), so no two keys meet here."""
    fields = {}
    for key, value in table.items():
        name = prefix + key.lower()
        if isinstance(value, dict):
            fields.update(_flat(value, name + "."))
        else:
            fields[name] = value
    return fields


def _hash(secret: str) -> str:
    """The SHA-256 the plugin compares a secret with, or "" for no secret."""
    return hashlib.sha256(secret.encode()).hexdigest() if secret else ""


def _proxy(fields: dict) -> dict | None:
    """The policy entry of a proxy table, or None if the plugin could not read it: frpc
    reads these fields as strings and refuses its whole config otherwise."""
    tunnel_type = fields.get("type")
    custom_domains = fields.get("customdomains", [])
    subdomain = fields.get("subdomain", "")
    group = fields.get("loadbalancer.group", "")
    group_key = fields.get("loadbalancer.groupkey", "")
    allow_users = fields.get("allowusers", [])
    secret_key = fields.get("secretkey", "")
    if (
        tunnel_type not in _TYPES
        or not isinstance(custom_domains, list)
        or not all(isinstance(domain, str) for domain in custom_domains)
        or not isinstance(subdomain, str)
        or not isinstance(group, str)
        or not isinstance(group_key, str)
        or not isinstance(allow_users, list)
        or not all(isinstance(user, str) for user in allow_users)
        or not isinstance(secret_key, str)
    ):
        return None
    return {
        "type": tunnel_type,
        "customDomains": custom_domains,
        "subdomain": subdomain,
        "group": group,
        "groupKeyHash": _hash(group_key),
        "allowUsers": allow_users,
        "skHash": _hash(secret_key),
    }


def _proxies(
    db: Session, config: FrpServerConfig, server_id: str, tunnels: list[FrpTunnel]
) -> dict:
    """The proxies of the host's frpc.toml by tunnel ID."""
    try:
        doc = tomllib.loads(
            generate_frpc_toml(config, tunnels, server_id, get_allow_users(db, server_id))
        )
    except tomllib.TOMLDecodeError:
        if _first_warning(repr(server_id), ("policy", "toml")):
            logger.warning("frpc.toml of server %r is no TOML, left out of the policy", server_id)
        return {}
    proxies = {}
    for table in doc.get("proxies", []):
        fields = _flat(table)
        name = fields.get("name")
        entry = _proxy(fields)
        # The plugin refuses the whole file for a proxy without an ID.
        if entry is None or not isinstance(name, str) or not name:
            if _first_warning(repr(name), ("policy", "fields")):
                logger.warning(
                    "FRP tunnel %r has a name, type or field the plugin cannot read, "
                    "left out of the policy",
                    name,
                )
            continue
        proxies[name] = entry
    return proxies


def _servers(db: Session) -> dict:
    """The hosts with at least one proxy the plugin can read, by server ID, before the
    domain conflicts are taken out. Without an FRP config no host has one
    (frpc_sync_inputs)."""
    servers: dict = {}
    config = get_frp_config(db)
    if config is None:
        return servers
    by_server: dict[str, list[FrpTunnel]] = defaultdict(list)
    for tunnel in db.query(FrpTunnel).filter(FrpTunnel.frp_config_id == config.id):
        by_server[tunnel.server_id].append(tunnel)
    for server_id, tunnels in sorted(by_server.items()):
        # frps names a proxy "<user>.<name>" and the plugin cuts the user off at the first
        # dot after it; a dot in the user would make that split ambiguous.
        if not server_id or "." in server_id:
            if _first_warning(repr(server_id), ("policy", "server id")):
                logger.warning(
                    "server ID %r is empty or has a dot, its tunnels are left out of the policy",
                    server_id,
                )
            continue
        proxies = _proxies(db, config, server_id, tunnels)
        if proxies:
            servers[server_id] = {"keyHash": proxy_key_hash(server_id), "proxies": proxies}
    return servers


def _conflicts(servers: dict) -> dict[str, set[str]]:
    """The custom domains (trimmed, lower case: hostnames match without regard to case)
    that proxies of more than one server carry without one non-empty group all of them
    share, with those servers."""
    carriers: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for server_id, entry in servers.items():
        for proxy in entry["proxies"].values():
            for domain in proxy["customDomains"]:
                carriers[domain.strip().lower()].add((server_id, proxy["group"]))
    conflicts = {}
    for domain, pairs in carriers.items():
        server_ids = {server_id for server_id, _ in pairs}
        groups = {group for _, group in pairs}
        if len(server_ids) > 1 and (len(groups) > 1 or "" in groups):
            conflicts[domain] = server_ids
    return conflicts


def domain_conflicts(db: Session) -> dict[str, set[str]]:
    """The custom domains the policy leaves out, with the servers that carry them."""
    return _conflicts(_servers(db))


def build_policy(db: Session) -> dict:
    """The policy for the DB's state: the hosts with at least one proxy, by server ID,
    without the proxies that carry a conflicting domain (domain_conflicts)."""
    servers = _servers(db)
    conflicts = _conflicts(servers)
    for domain in sorted(conflicts):
        if _first_warning(repr(domain), ("policy", "domain")):
            logger.warning(
                "custom domain %r is used by tunnels of several servers without one shared "
                "loadBalancer.group, their proxies are left out of the policy",
                domain,
            )
    for server_id in sorted({s for server_ids in conflicts.values() for s in server_ids}):
        proxies = servers[server_id]["proxies"]
        for name in [
            name
            for name, proxy in proxies.items()
            if any(d.strip().lower() in conflicts for d in proxy["customDomains"])
        ]:
            del proxies[name]
        if not proxies:
            del servers[server_id]
    return {"servers": servers, "version": POLICY_VERSION}


def policy_text(db: Session) -> str:
    """The file's text: sorted keys, so the same state gives the same bytes."""
    return json.dumps(build_policy(db), sort_keys=True, indent=2) + "\n"


def sync_policy(db: Session) -> None:
    """Writes the policy for the DB's state, best effort: the DB stays the source of truth
    and the next sync writes what this one could not. A failure rolls db back and is logged
    with its type alone (a psycopg error quotes the connection string), so a request goes on
    with its own work."""
    try:
        write_frps_policy(policy_text(db))
    except Exception as exc:
        db.rollback()
        logger.error("frps policy not written (%s)", type(exc).__name__)


def _sync_in_own_session() -> None:
    db = database.SessionLocal()
    try:
        sync_policy(db)
    finally:
        db.close()


async def keep_policy_current() -> None:
    """Syncs the policy every SYNC_INTERVAL seconds until cancelled: it puts back a file
    that was removed or changed and takes over a change no hook saw (a restored DB)."""
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        try:
            await asyncio.to_thread(_sync_in_own_session)
        except Exception as exc:
            logger.error("frps policy sync failed (%s)", type(exc).__name__)
