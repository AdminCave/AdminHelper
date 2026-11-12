# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor rdap of central checks (R-1224): registration status and expiry of a domain.

It asks the registry, not the host. The IANA bootstrap (RFC 9224) names the RDAP
server of the top-level domain; .de is not listed there, DENIC runs a pilot service
of its own whose answers carry the status but no expiry date. One GET for the domain
(RFC 9082) gives the verdict: a status that takes the domain out of DNS or deletes
it (RFC 9083 §10.2.2) is critical, so is an expiry date closer than `crit_days`,
one closer than `warn_days` a warning.

The registered domain is found once: of the host and its parent domains, the three
nearest the top-level domain are asked, the longest first, and the first the registry
knows is kept in the state. That also finds a domain under a two-label suffix such as
co.uk, without a public suffix list. Later runs ask for the kept domain alone; a 404 there says it is
registered no longer. A domain on hold has left DNS, which is why the search does
not go through DNS.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import ValidationError

from app.central import fetch
from app.central.tls import SensorResult
from app.check_configs import RdapParams
from app.core.time import iso_utc

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_TTL = timedelta(days=1)
BOOTSTRAP_RETRY = timedelta(minutes=15)
# The file held 71 kB on 2026-11-12, above the default bound of fetch.
BOOTSTRAP_MAX_BODY = 512 * 1024
# Registries the bootstrap does not list, from their own documentation (2026-11-12).
EXTRA_SERVERS = {"de": "https://rdap.denic.de/"}
ACCEPT = "application/rdap+json"
MAX_TRIES = 3
MAX_STATUS = 16
MAX_STATUS_TEXT = 64
MAX_TEXT = 200

# RFC 9083 §10.2.2 status values, compared without case, spaces, hyphens and
# underscores, so that the EPP spelling (clientHold) matches as well.
CRITICAL_STATUS = {
    "clienthold": "on hold by the registrar, out of DNS",
    "serverhold": "on hold by the registry, out of DNS",
    "redemptionperiod": "deleted, in the redemption period",
    "pendingdelete": "pending delete",
}
_SEPARATORS = re.compile(r"[\s_-]+")
_LONG_AGO = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Bootstrap:
    servers: dict[str, str] | None = None
    fetched_at: datetime = _LONG_AGO
    failed_at: datetime = _LONG_AGO
    error: str = ""


_bootstrap_lock = threading.Lock()
_bootstrap = _Bootstrap()


def probe(
    host: str, params: dict, prev: dict | None = None, *, now: datetime | None = None
) -> SensorResult:
    """The verdict on the domain of `host`; `prev` holds the previous details."""
    now = now or datetime.now(timezone.utc)
    host = host.lower().rstrip(".")
    old = (prev or {}).get("rdap")
    known = old.get("domain") if isinstance(old, dict) else None
    known = known if isinstance(known, str) and _within(known, host) else None
    candidates = [known] if known else _candidates(host)
    if not candidates:
        return SensorResult("unknown", f"{host} is a top-level domain"[:MAX_TEXT], False)
    try:
        servers = _servers(now)
    except fetch.FetchError as exc:
        return SensorResult("unknown", f"IANA RDAP bootstrap: {exc}"[:MAX_TEXT], False)

    for name in candidates:
        base = _server_for(name, servers)
        if base is None:
            tld = name.rsplit(".", 1)[-1]
            return SensorResult("unknown", f"no RDAP service for .{tld}", False)
        server = httpx.URL(base).host
        try:
            answer = fetch.get(f"{base}domain/{name}", accept=ACCEPT)
        except fetch.FetchError as exc:
            return SensorResult("unknown", f"RDAP {server}: {exc}"[:MAX_TEXT], False)
        if answer.status == 404:
            if known:
                details = {"domain": name, "server": base, "registered": False}
                details["checked_at"] = iso_utc(now)
                message = f"{name} is no longer registered ({server} answers 404)"[:MAX_TEXT]
                return SensorResult("critical", message, True, details={"rdap": details})
            continue
        if answer.status == 429:
            return SensorResult("unknown", f"RDAP {server}: rate limited (HTTP 429)", False)
        if answer.status != 200:
            return SensorResult("unknown", f"RDAP {server}: HTTP {answer.status}", False)
        return _verdict(name, host, base, answer.body, params, now)

    tried = " or its parent domains" if len(candidates) > 1 else ""
    message = f"no registration found for {host}{tried}"[:MAX_TEXT]
    return SensorResult("unknown", message, False)


def _verdict(
    name: str, host: str, base: str, body: bytes, params: dict, now: datetime
) -> SensorResult:
    server = httpx.URL(base).host
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return SensorResult("unknown", f"RDAP {server}: no RDAP JSON object", False)
    ldh = data.get("ldhName")
    if isinstance(ldh, str):
        ldh = ldh.lower().rstrip(".")
        # A registry may answer for the domain that holds the name asked for.
        if not _within(ldh, name) or "." not in ldh:
            return SensorResult("unknown", f"RDAP {server}: answer for another name", False)
        name = ldh
    status = _status(data.get("status"))
    expires = _expiration(data.get("events"))
    details = {
        "domain": name,
        "server": base,
        "registered": True,
        "status": status,
        "expires": iso_utc(expires),
        "checked_at": iso_utc(now),
    }
    metrics = {}
    if expires is not None:
        days_left = (expires - now).total_seconds() / 86400
        metrics["days_left"] = round(days_left, 2)

    holds = [CRITICAL_STATUS[k] for k in dict.fromkeys(map(_key, status)) if k in CRITICAL_STATUS]
    if holds:
        verdict, message = "critical", f"{name}: {', '.join(holds)}"
    elif expires is None:
        shown = ", ".join(status) or "none given"
        verdict = "ok"
        message = f"{name} is registered (status {shown}); the registry publishes no expiry date"
    else:
        warn_days, crit_days = _thresholds(params)
        date = expires.date().isoformat()
        if days_left < 0:
            verdict, message = "critical", f"{name} expired on {date}"
        else:
            verdict = "critical" if days_left < crit_days else "ok"
            if verdict == "ok" and days_left < warn_days:
                verdict = "warning"
            message = f"{name} expires on {date} ({_in_days(days_left)})"
    return SensorResult(verdict, message[:MAX_TEXT], True, metrics, {"rdap": details})


def _candidates(host: str) -> list[str]:
    """Of the host and its parents above the top-level domain, the MAX_TRIES nearest the top,
    longest first."""
    labels = host.split(".")
    names = [".".join(labels[i:]) for i in range(len(labels) - 1)]
    return names[-MAX_TRIES:]


def _within(name: str, host: str) -> bool:
    return host == name or host.endswith(f".{name}")


def _server_for(name: str, servers: dict[str, str]) -> str | None:
    """RFC 9224 §4: the longest listed suffix of `name` names its server."""
    labels = name.split(".")
    for i in range(1, len(labels)):
        base = servers.get(".".join(labels[i:]))
        if base is not None:
            return base
    return EXTRA_SERVERS.get(labels[-1])


def _servers(now: datetime) -> dict[str, str]:
    """The bootstrap, fetched at most daily; after a failure the old copy serves on."""
    global _bootstrap
    with _bootstrap_lock:
        cached = _bootstrap
    if cached.servers is not None and now - cached.fetched_at < BOOTSTRAP_TTL:
        return cached.servers
    if now - cached.failed_at < BOOTSTRAP_RETRY:
        if cached.servers is not None:
            return cached.servers
        raise fetch.FetchError(cached.error)
    try:
        servers = _load_bootstrap()
    except fetch.FetchError as exc:
        with _bootstrap_lock:
            _bootstrap = _Bootstrap(_bootstrap.servers, _bootstrap.fetched_at, now, str(exc))
        if cached.servers is not None:
            return cached.servers
        raise
    with _bootstrap_lock:
        _bootstrap = _Bootstrap(servers, now)
    return servers


def _load_bootstrap() -> dict[str, str]:
    answer = fetch.get(BOOTSTRAP_URL, max_body=BOOTSTRAP_MAX_BODY)
    if answer.status != 200:
        raise fetch.FetchError(f"HTTP {answer.status}")
    try:
        servers = _parse_bootstrap(answer.body)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
        raise fetch.FetchError("unreadable file") from None
    if not servers:
        raise fetch.FetchError("no https server listed")
    return servers


def _parse_bootstrap(body: bytes) -> dict[str, str]:
    """RFC 9224 §4: `services` holds [[labels], [base URLs]]; the first https URL serves."""
    servers: dict[str, str] = {}
    for entry in json.loads(body)["services"]:
        labels, urls = entry[0], entry[1]
        if not isinstance(labels, list) or not isinstance(urls, list):
            continue
        url = next((u for u in urls if _https(u)), None)
        if url is None:
            continue
        url = url if url.endswith("/") else f"{url}/"
        for label in labels:
            if isinstance(label, str) and label:
                servers.setdefault(label.lower().rstrip("."), url)
    return servers


def _https(url: object) -> bool:
    return (
        isinstance(url, str)
        and url.startswith("https://")
        and len(url) <= MAX_TEXT
        and url.isprintable()
        and " " not in url
    )


def _status(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found = [s[:MAX_STATUS_TEXT] for s in value if isinstance(s, str) and s.isprintable()]
    return found[:MAX_STATUS]


def _key(status: str) -> str:
    return _SEPARATORS.sub("", status.lower())


def _expiration(events: object) -> datetime | None:
    if not isinstance(events, list):
        return None
    for event in events:
        if isinstance(event, dict) and str(event.get("eventAction")).lower() == "expiration":
            when = _parse_time(event.get("eventDate"))
            if when is not None:
                return when
    return None


def _thresholds(params: dict) -> tuple[int, int]:
    try:
        checked = RdapParams.model_validate(params)
    except ValidationError:
        checked = RdapParams()
    return checked.warn_days, checked.crit_days


def _in_days(days_left: float) -> str:
    if days_left < 1:
        return "within a day"
    days = int(days_left)
    return f"in {days} day{'s' if days != 1 else ''}"


def _parse_time(value: object) -> datetime | None:
    """An RFC 3339 time with offset; None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None
