# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Tailscale client tailscaled from its package (R-1236).

Beside the unit the agent's app sensor asks `tailscale status --json --peers=false` and
reports whether the node is connected (backend state Running), how many health warnings
tailscaled has and in how many days the node key expires; no address, name or key, and no
netcheck. A node that is not connected is critical. The key's expiry is a check of its own,
asked hourly: below 14 days it warns, since an expired key drops the node off the tailnet.
A node with key expiry turned off reports no expiry and that check stays unknown: turn it
off there.

Not covered: the image tailscale/tailscale, peers and their reachability, and the
coordination server (see the module headscale).
"""

_STATUS_FIELDS = ["backend_running", "health_warnings", "key_expiry_days"]

MODULE = {
    "id": "tailscale",
    "name": "Tailscale",
    "version": 1,
    "description": (
        "The Tailscale client: the unit, whether the node is connected and when its key expires."
    ),
    "detect": {"units": ["tailscaled.service"]},
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
            "key": "connected",
            "name": "Connected",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "tailscale_status"},
            "interval": 300,
            "fields": _STATUS_FIELDS,
            "rules": [
                {"field": "backend_running", "op": "eq", "value": False, "level": "critical"}
            ],
        },
        {
            "key": "key_expiry",
            "name": "Key expiry",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "tailscale_status"},
            "interval": 3600,
            "fields": _STATUS_FIELDS,
            "rules": [{"field": "key_expiry_days", "op": "lt", "value": 14, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "connected", "field": "backend_running", "label": "Connected"},
        {"check_key": "key_expiry", "field": "key_expiry_days", "label": "Key expires in days"},
    ],
}
