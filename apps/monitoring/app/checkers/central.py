# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The check type `central`: probes the monitoring service runs itself (R-1224).

Per run: one of the parallel slots, the rule public/internal for the host, then
the sensor against the global addresses the rule handed on. A target that was
public once (`public_since` in the details) stays watched: a later failure to
reach it is critical, never a quiet move to "checked by the agent".

A sensor that asks a registry about the host instead of the host itself (rdap)
skips the rule: the host need not have an address, a mail-only domain has none,
and the agent could not ask the registry in its place either.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.central import dns as dns_sensor
from app.central import mail, rdap, resolve, tls
from app.central.limits import LIMITS, SKIPPED_BUSY_MESSAGE, RunSkipped
from app.central.resolve import Classification, Reach
from app.central.tls import SensorResult
from app.check_configs import CENTRAL_SENSORS
from app.checkers.context import CheckContext
from app.core.time import iso_utc

# host, the rule for it, port (None for a sensor without one), params, the previous
# details for this host.
Probe = Callable[[str, Classification, int | None, dict, dict], SensorResult]


def _tls(
    host: str, rule: Classification, port: int | None, params: dict, prev: dict
) -> SensorResult:
    return tls.probe(host, rule.addresses, port, prev)


def _dns(
    host: str, rule: Classification, port: int | None, params: dict, prev: dict
) -> SensorResult:
    return dns_sensor.probe(host, rule, params, prev)


def _mail(
    host: str, rule: Classification, port: int | None, params: dict, prev: dict
) -> SensorResult:
    assert port is not None  # both mail sensors have a default port
    return mail.probe(host, rule.addresses, port)


_PROBES: dict[str, Probe] = {"tls": _tls, "dns": _dns, "smtp": _mail, "imap": _mail}
# host, params, the previous details for this host.
RegistryProbe = Callable[[str, dict, dict], SensorResult]
_REGISTRY_PROBES: dict[str, RegistryProbe] = {"rdap": rdap.probe}
# The states a sensor carries from run to run. A run that does not reach the target
# hands them on unchanged, so that the next one does not start over.
_KEPT: dict[str, tuple[str, ...]] = {
    "tls": ("ari", "caa"),
    "dns": ("baseline", "zone"),
    "rdap": ("rdap",),
}


class CentralChecker:
    wants_context = True

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return self.run_with_context(config, CheckContext())

    def run_with_context(self, config: dict, context: CheckContext) -> tuple[str, str, dict | None]:
        sensor, host = config.get("sensor"), config.get("host")
        probe = _PROBES.get(sensor) if isinstance(sensor, str) else None
        registry = _REGISTRY_PROBES.get(sensor) if isinstance(sensor, str) else None
        if (probe is None and registry is None) or not isinstance(host, str) or not host:
            return "unknown", f"Unknown sensor or no host: {sensor!r}", None
        port = config.get("port") or CENTRAL_SENSORS[sensor].default_port
        params = config.get("params")
        params = params if isinstance(params, dict) else {}
        prev = context.prev_details or {}
        # A changed host starts over: the old one's history says nothing about it.
        if prev.get("host") != host:
            prev = {}
        if registry is not None:
            return _ask_registry(registry, sensor, host, params, prev)
        public_since = prev.get("public_since")

        silence = None
        with LIMITS.slot() as acquired:
            if not acquired:
                raise RunSkipped(SKIPPED_BUSY_MESSAGE)
            rule = resolve.classify(host)
            result = probe(host, rule, port, params, prev) if rule.reach is Reach.PUBLIC else None
            if rule.reach is Reach.RESOLVERS_UNREACHABLE and sensor == "dns":
                # For the sensor dns a name no resolver answers for may itself be the finding.
                silence = dns_sensor.diagnose_silence(host)

        details: dict = {"host": host}
        if port is not None:
            details["port"] = port
        if result is None or not result.reached:
            details.update({k: prev[k] for k in _KEPT.get(sensor, ()) if k in prev})
        if rule.notes:
            details["notes"] = list(rule.notes)
        if rule.reach is Reach.RESOLVERS_UNREACHABLE:
            if silence:
                if public_since:
                    return "critical", silence, _with(details, public_since)
                return "unknown", f"{resolve.NOT_PUBLIC_MESSAGE} ({silence})", _with(details, None)
            # Our own way out is down, not the target: no verdict, the history stays.
            return "unknown", rule.message, _with(details, public_since)
        if rule.reach is Reach.NOT_PUBLIC:
            why = _join(rule.notes)
            if public_since:
                return "critical", f"{host} is no longer public{why}", _with(details, public_since)
            return "unknown", f"{rule.message}{why}", _with(details, None)

        assert result is not None  # Reach.PUBLIC
        details.update(result.details)
        details["addresses"] = list(rule.addresses)
        if not result.reached:
            if public_since:
                return "critical", result.message, _with(details, public_since, result.metrics)
            message = f"{resolve.NOT_PUBLIC_MESSAGE} ({result.message})"
            return "unknown", message, _with(details, None, result.metrics)
        since = public_since or iso_utc(datetime.now(timezone.utc))
        return result.status, result.message, _with(details, since, result.metrics)


def _ask_registry(
    probe: RegistryProbe, sensor: str, host: str, params: dict, prev: dict
) -> tuple[str, str, dict]:
    with LIMITS.slot() as acquired:
        if not acquired:
            raise RunSkipped(SKIPPED_BUSY_MESSAGE)
        result = probe(host, params, prev)
    details: dict = {"host": host}
    if not result.reached:
        details.update({k: prev[k] for k in _KEPT.get(sensor, ()) if k in prev})
    details.update(result.details)
    return result.status, result.message, _with(details, None, result.metrics)


def _with(details: dict, public_since: str | None, metrics: dict | None = None) -> dict:
    if public_since:
        details["public_since"] = public_since
    return {**(metrics or {}), "_details": details}


def _join(notes: tuple[str, ...]) -> str:
    return f" ({'; '.join(notes)})" if notes else ""
