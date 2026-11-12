# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The check type `central`: probes the monitoring service runs itself (R-1224).

Per run: one of the parallel slots, the rule public/internal for the host, then
the sensor against the global addresses the rule handed on. A target that was
public once (`public_since` in the details) stays watched: a later failure to
reach it is critical, never a quiet move to "checked by the agent".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app.central import resolve, tls
from app.central.limits import LIMITS, SKIPPED_BUSY_MESSAGE, RunSkipped
from app.central.resolve import Reach
from app.central.tls import SensorResult
from app.check_configs import CENTRAL_SENSORS
from app.checkers.context import CheckContext
from app.core.time import iso_utc

Probe = Callable[[str, tuple[str, ...], int], SensorResult]

_PROBES: dict[str, Probe] = {"tls": tls.probe}


class CentralChecker:
    wants_context = True

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return self.run_with_context(config, CheckContext())

    def run_with_context(self, config: dict, context: CheckContext) -> tuple[str, str, dict | None]:
        sensor, host = config.get("sensor"), config.get("host")
        probe = _PROBES.get(sensor) if isinstance(sensor, str) else None
        if probe is None or not isinstance(host, str) or not host:
            return "unknown", f"Unknown sensor or no host: {sensor!r}", None
        port = config.get("port") or CENTRAL_SENSORS[sensor].default_port
        prev = context.prev_details or {}
        # A changed host starts over: the old one's history says nothing about it.
        public_since = prev.get("public_since") if prev.get("host") == host else None

        with LIMITS.slot() as acquired:
            if not acquired:
                raise RunSkipped(SKIPPED_BUSY_MESSAGE)
            rule = resolve.classify(host)
            result = probe(host, rule.addresses, port) if rule.reach is Reach.PUBLIC else None

        details: dict = {"host": host, "port": port}
        if rule.notes:
            details["notes"] = list(rule.notes)
        if rule.reach is Reach.RESOLVERS_UNREACHABLE:
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


def _with(details: dict, public_since: str | None, metrics: dict | None = None) -> dict:
    if public_since:
        details["public_since"] = public_since
    return {**(metrics or {}), "_details": details}


def _join(notes: tuple[str, ...]) -> str:
    return f" ({'; '.join(notes)})" if notes else ""
