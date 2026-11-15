# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SpamAssassin's daemon spamd from its unit (R-1239).

The module is found by spamd.service (Debian, Ubuntu since SpamAssassin 4) or
spamassassin.service (older Debian; RHEL not verified). Every 5 minutes the agent's app sensor
sends spamd a PING with spamc -K and reads only whether spamd answers; no answer is critical.
No mail is scanned and no rule is updated (sa-update).

Not covered: spamd on another host or port, the age of the rules, and the Bayes database.
"""

MODULE = {
    "id": "spamassassin",
    "name": "SpamAssassin",
    "version": 1,
    "description": "SpamAssassin's spamd from its unit: the unit and its answer to a PING.",
    "detect": {"units": ["spamd.service", "spamassassin.service"]},
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
            "key": "ping",
            "name": "Ping",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "spamd_ping"},
            "interval": 300,
            "fields": ["reachable"],
            "rules": [{"field": "reachable", "op": "eq", "value": False, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "ping", "field": "reachable", "label": "Answers PING"},
    ],
}
