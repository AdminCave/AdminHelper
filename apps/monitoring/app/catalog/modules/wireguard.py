# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WireGuard interfaces brought up by wg-quick@<interface> (R-1236).

Each unit wg-quick@<interface> is an instance. Beside the unit the agent's app sensor reads
the age of each peer's latest handshake and its persistent keepalive with `wg show all
latest-handshakes` and `wg show all persistent-keepalive`, keeping the instance's interface
(never `dump` or `showconf`, which print keys) and reports counts only, no key,
no endpoint, no allowed address. Stale counts only peers with a persistent keepalive: a peer
without one shakes hands only while it sends, so an idle road warrior is no finding. A
keepalive peer without a handshake for more than 5 minutes warns, for more than 15 minutes
it is critical; WireGuard renews a session every two minutes while packets flow.

Not covered: interfaces of systemd-networkd, NetworkManager or wg-quick run by hand (no unit
of their own), and the transfer counters.
"""

MODULE = {
    "id": "wireguard",
    "name": "WireGuard",
    "version": 1,
    "description": (
        "WireGuard interfaces of wg-quick: the unit and how many peers with a keepalive "
        "have not shaken hands for a while."
    ),
    "detect": {"units": ["wg-quick@.service"]},
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
            "key": "peers",
            "name": "Peers",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "wg_peers"},
            "interval": 300,
            "fields": [
                "interfaces",
                "peers",
                "keepalive_peers",
                "stale_warn",
                "stale_crit",
                "max_handshake_age_s",
            ],
            "rules": [
                {"field": "stale_crit", "op": "gt", "value": 0, "level": "critical"},
                {"field": "stale_warn", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "peers", "field": "peers", "label": "Peers"},
        {"check_key": "peers", "field": "stale_crit", "label": "Stale peers"},
    ],
}
