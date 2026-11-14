# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""fail2ban from its package (R-1236).

Beside the unit the agent's app sensor asks fail2ban-client `ping`, `status` and `status
<jail>` and reports whether the server answers, the number of jails, the bans in total and
of the fullest jail, and the jails that watch no file. It never reports a banned address or
a jail's name and never unbans, reloads or sets anything. A server that does not answer is
critical: the unit can be active while the socket is dead. A jail whose file list is empty
warns: its log path matched nothing, so it bans no one (a jail of the systemd backend
shows journal matches instead of a file list and does not count). More than 10000 bans in
one jail warns: a large ban list slows fail2ban and the firewall.

Daily the agent runs `fail2ban-client --test` and reports only whether the configuration loads: one
that does not would fail the next restart or reload while the running server goes on, a
warning.
"""

MODULE = {
    "id": "fail2ban",
    "name": "fail2ban",
    "version": 2,
    "description": (
        "fail2ban: the unit, whether the server answers, its jails and how many addresses they ban."
    ),
    "detect": {"units": ["fail2ban.service"]},
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
            "key": "jails",
            "name": "Jails",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "fail2ban"},
            "interval": 300,
            "fields": ["responding", "jails", "banned_total", "max_banned", "jails_without_files"],
            "rules": [
                {"field": "responding", "op": "eq", "value": False, "level": "critical"},
                {"field": "jails_without_files", "op": "gt", "value": 0, "level": "warning"},
                {"field": "max_banned", "op": "gt", "value": 10000, "level": "warning"},
            ],
        },
        {
            "key": "config",
            "name": "Configuration test",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "service_config"},
            "interval": 86400,
            "timeout_s": 20,
            "fields": ["config_ok"],
            "rules": [{"field": "config_ok", "op": "eq", "value": False, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "jails", "field": "jails", "label": "Jails"},
        {"check_key": "jails", "field": "banned_total", "label": "Banned"},
    ],
}
