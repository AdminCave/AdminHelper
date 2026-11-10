# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A listening TCP port no other module claims (monitoring concept §3.12, stage 4).

The agent's discovery recognises the protocol on such a port; the check asks the
same way, so an adopted port is watched in its own protocol, not by a bare connect.
"""

MODULE = {
    "id": "port",
    "name": "Listening port",
    "version": 1,
    "description": (
        "A TCP port that listens on a non-loopback address and belongs to no known "
        "service. Checked in the protocol the agent recognised on it."
    ),
    "instance": "port",
    "checks": [
        {
            "key": "answers",
            "name": "Port answers",
            "sensor": "proto",
            "target": {"kind": "port"},
            "params": {"protocol": "auto"},
            "interval": 900,
            "fields": ["ok", "detail", "tls_ok", "duration_ms"],
            "rules": [{"field": "ok", "op": "eq", "value": False, "level": "critical"}],
        }
    ],
    "card": [
        {"check_key": "answers", "field": "detail", "label": "Protocol"},
        {"check_key": "answers", "field": "duration_ms", "label": "Response (ms)"},
    ],
}
