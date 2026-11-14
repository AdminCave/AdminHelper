# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows Server Update Services (R-1246).

The service WsusService finds the module. The agent reports the free space of the volume the
update content lies on and the day's error events of WSUS; no synchronisation time (it lives
only in the WSUS database or its .NET API, Kevin 2026-11-14). Below 10 per cent free is a
warning, below 5 critical; an error event a warning. Sync and cleanup are never started.
Not verified on a WSUS server.
"""

MODULE = {
    "id": "wsus",
    "name": "WSUS",
    "version": 1,
    "description": "WSUS: the service, free space for the update content, error events.",
    "detect": {"units": ["WsusService.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Service",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "content",
            "name": "Content and events",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "wsus"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["content_free_bytes", "content_free_pct", "errors_24h"],
            "rules": [
                {"field": "content_free_pct", "op": "lt", "value": 5, "level": "critical"},
                {"field": "content_free_pct", "op": "lt", "value": 10, "level": "warning"},
                {"field": "errors_24h", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "content", "field": "content_free_pct", "label": "Content free %"},
        {"check_key": "content", "field": "errors_24h", "label": "Errors (24 h)"},
    ],
}
