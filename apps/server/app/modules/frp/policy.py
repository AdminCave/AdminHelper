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

A hostname that frps routes to proxies of several servers is left out for all of them
(domain_conflicts): frps hands it to whichever proxy registers first, and a wildcard takes
the traffic of a name below it while that name's proxy is down. Only the same exact name in
one non-empty group all of them share is no conflict. The tunnel API refuses to store a new
one."""

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
from app.modules.servers.models import Server

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
    db: Session,
    config: FrpServerConfig,
    server_id: str,
    key_generation: int,
    tunnels: list[FrpTunnel],
) -> dict:
    """The proxies of the host's frpc.toml by tunnel ID."""
    try:
        doc = tomllib.loads(
            generate_frpc_toml(
                config,
                tunnels,
                server_id,
                get_allow_users(db, server_id),
                key_generation=key_generation,
            )
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


def _servers(db: Session) -> tuple[dict, str]:
    """The hosts with at least one proxy the plugin can read, by server ID, before the
    domain conflicts are taken out, and the FRP config's subdomain host. Without an FRP
    config no host has one (frpc_sync_inputs)."""
    servers: dict = {}
    config = get_frp_config(db)
    if config is None:
        return servers, ""
    by_server: dict[str, list[FrpTunnel]] = defaultdict(list)
    for tunnel in db.query(FrpTunnel).filter(FrpTunnel.frp_config_id == config.id):
        by_server[tunnel.server_id].append(tunnel)
    generations = dict(
        db.query(Server.id, Server.frp_key_generation).filter(Server.id.in_(by_server.keys()))
    )
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
        generation = generations.get(server_id, 0)
        proxies = _proxies(db, config, server_id, generation, tunnels)
        if proxies:
            servers[server_id] = {
                "keyHash": proxy_key_hash(server_id, generation),
                "proxies": proxies,
            }
    return servers, (config.subdomain_host or "").strip().lower()


def _hostnames(proxy: dict, subdomain_host: str) -> set[str]:
    """The names frps routes to the proxy (frp v0.72 BaseProxy.buildDomains), trimmed and
    in lower case: frps matches hostnames without regard to case."""
    names = {d.strip().lower() for d in proxy["customDomains"] if d.strip()}
    subdomain = proxy["subdomain"].strip().lower()
    if subdomain and subdomain_host:
        names.add(f"{subdomain}.{subdomain_host}")
    return names


def _covers(pattern: str, name: str) -> bool:
    """Whether frps may route name to a proxy of pattern (vhost Routers.getByRoute): the same
    name, "*" for all, "*.example.net" for every name below example.net. A superset of what
    frps routes: it never matches a two-label name against a wildcard, so "*.com" covers
    "example.com" here but not in frps."""
    return (
        pattern == name
        or pattern == "*"
        or (pattern.startswith("*.") and name.endswith(pattern[1:]))
    )


def _conflicts(servers: dict, subdomain_host: str) -> dict[str, set[tuple[str, str]]]:
    """The hostnames frps would route to proxies of more than one server, with those
    proxies as (server ID, proxy name). Only the same exact name in one non-empty group
    is no conflict: frps balances a group, and a wildcard is a router of its own."""
    carriers = [
        (name, server_id, proxy_name, proxy["group"])
        for server_id, entry in servers.items()
        for proxy_name, proxy in entry["proxies"].items()
        # frps builds hostnames only for HTTP(S) proxies; a subdomain on an STCP proxy routes nothing.
        if proxy["type"] == "https"
        for name in _hostnames(proxy, subdomain_host)
    ]
    conflicts: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for i, (name, server_id, proxy_name, group) in enumerate(carriers):
        for other, other_server, other_proxy, other_group in carriers[i + 1 :]:
            if server_id == other_server:
                continue
            if not (_covers(name, other) or _covers(other, name)):
                continue
            if name == other and group and group == other_group:
                continue
            for conflict in (name, other):
                conflicts[conflict] |= {(server_id, proxy_name), (other_server, other_proxy)}
    return dict(conflicts)


def domain_conflicts(db: Session) -> dict[str, set[tuple[str, str]]]:
    """The hostnames the policy leaves out, with the proxies (server ID, proxy name) that
    carry them."""
    return _conflicts(*_servers(db))


def build_policy(db: Session) -> dict:
    """The policy for the DB's state: the hosts with at least one proxy, by server ID,
    without the proxies that carry a conflicting domain (domain_conflicts)."""
    servers, subdomain_host = _servers(db)
    conflicts = _conflicts(servers, subdomain_host)
    for name in sorted(conflicts):
        if _first_warning(repr(name), ("policy", "domain")):
            logger.warning(
                "hostname %r is routed to tunnels of several servers (custom domain, subdomain "
                "or wildcard) without one shared loadBalancer.group, their proxies are left out "
                "of the policy",
                name,
            )
    for server_id, proxy_name in sorted(set().union(*conflicts.values())):
        proxies = servers[server_id]["proxies"]
        proxies.pop(proxy_name, None)
        if not proxies:
            servers.pop(server_id, None)
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
