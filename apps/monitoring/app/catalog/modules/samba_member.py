# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Samba as a file server or domain member, from the unit of smbd (R-1240).

The module is found by smbd.service. Every 15 minutes the agent's app sensor asks testparm -s
whether smb.conf holds no error (an error warns) and counts the sessions, share connections
and open files from smbstatus --json --fast (Samba 4.17 or later; an older Samba leaves just
these three numbers out, the other checks of the view stay). The same view asks winbind
with wbinfo -p whether it answers (critical if not) and wbinfo -P whether it reaches its domain
controller (warning if not); once a day wbinfo -t checks the trust account of the member
(warning if not valid). A file server without winbind has neither answer, and the checks domain
and trust stay unknown there: turn them off. No share, user, client or file name leaves the
host.

Not covered: the paths of the shares and their fill level (module of the file systems), and
the smbd of an AD DC (samba-ad-dc runs its own, module samba-ad-dc).
"""

_VIEW = {"view": "samba_member"}

MODULE = {
    "id": "samba-member",
    "name": "Samba file server",
    "version": 1,
    "description": (
        "Samba as a file server or domain member: the unit, the configuration, the sessions "
        "and open files, winbind and the trust account."
    ),
    "detect": {"units": ["smbd.service"]},
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
            "key": "status",
            "name": "Configuration and sessions",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": _VIEW,
            "interval": 900,
            "fields": ["config_ok", "sessions", "tcons", "open_files"],
            "rules": [{"field": "config_ok", "op": "eq", "value": False, "level": "warning"}],
        },
        {
            "key": "domain",
            "name": "Winbind",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": _VIEW,
            "interval": 900,
            "fields": ["winbind_ok", "dc_ok"],
            "rules": [
                {"field": "winbind_ok", "op": "eq", "value": False, "level": "critical"},
                {"field": "dc_ok", "op": "eq", "value": False, "level": "warning"},
            ],
        },
        {
            "key": "trust",
            "name": "Trust account",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "samba_trust"},
            "interval": 86400,
            "fields": ["trust_ok"],
            "rules": [{"field": "trust_ok", "op": "eq", "value": False, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "status", "field": "sessions", "label": "Sessions"},
        {"check_key": "status", "field": "open_files", "label": "Open files"},
        {"check_key": "domain", "field": "winbind_ok", "label": "Winbind"},
        {"check_key": "trust", "field": "trust_ok", "label": "Trust"},
    ],
}
