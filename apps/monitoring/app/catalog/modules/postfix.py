# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Postfix from its unit (R-1239).

The module is found by postfix.service (Debian, Ubuntu, RHEL). On Debian and Ubuntu it is a
oneshot that stays active (exited) while postfix@-.service runs the mail system, so the unit
alone does not show a dead master: every 5 minutes the agent also asks for the SMTP greeting on
port 25 of the loopback, and a missing or wrong greeting is critical. A Postfix whose
inet_interfaces leaves out the loopback fails this check: turn it off there. Every 5 minutes
the agent's app sensor counts the mails in the queues incoming, active, deferred and hold from
the directory entries of the queue directory postconf names, opening no queue file; more than 100 deferred mails warn, as does a count that stopped at its
cap. Every 15 minutes it reads the arrival times of postqueue -j, and nothing else of its
JSON, for the age of the oldest mail: older than a day warns, older than four days (Postfix's
maximal_queue_lifetime before it bounces, 5 d) is critical. With 5000 mails or more it does not
ask showq and age_read is false, which warns. A mail an admin holds counts as well. No
address, domain or queue ID leaves the host.

Not covered: further instances of postmulti, a queue directory outside the root of the
host, and the Postfix of Mailcow (module mailcow).
"""

_QUEUE_FIELDS = ["active", "capped", "deferred", "hold", "incoming", "total"]

MODULE = {
    "id": "postfix",
    "name": "Postfix",
    "version": 1,
    "description": (
        "Postfix from its unit: the unit, the mails in each queue and the age of the oldest "
        "mail in the queue."
    ),
    "detect": {"units": ["postfix.service"]},
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
            "key": "smtp",
            "name": "SMTP greeting",
            "sensor": "proto",
            "target": {"kind": "loopback", "port_hint": 25},
            "params": {"protocol": "smtp"},
            "interval": 300,
            "fields": ["ok", "detail", "duration_ms"],
            "rules": [{"field": "ok", "op": "eq", "value": False, "level": "critical"}],
        },
        {
            "key": "queue",
            "name": "Queue",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "postfix_queue"},
            "interval": 300,
            "fields": _QUEUE_FIELDS,
            "rules": [
                {"field": "deferred", "op": "gt", "value": 100, "level": "warning"},
                {"field": "capped", "op": "eq", "value": True, "level": "warning"},
            ],
        },
        {
            "key": "queue_age",
            "name": "Oldest mail",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "postfix_queue_age"},
            "interval": 900,
            "fields": ["age_read", "oldest_age_s"],
            "rules": [
                {"field": "age_read", "op": "eq", "value": False, "level": "warning"},
                {"field": "oldest_age_s", "op": "gt", "value": 86400, "level": "warning"},
                {"field": "oldest_age_s", "op": "gt", "value": 345600, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "smtp", "field": "detail", "label": "SMTP"},
        {"check_key": "queue", "field": "total", "label": "Mails queued"},
        {"check_key": "queue", "field": "deferred", "label": "Deferred"},
        {"check_key": "queue_age", "field": "oldest_age_s", "label": "Oldest mail s"},
    ],
}
