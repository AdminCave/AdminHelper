# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UrBackup server: the service and the state of its clients' backups (R-1233).

The module is found by urbackupsrv.service; a unit that is not active is critical. Every 15
minutes the agent's app sensor asks the server's web interface on its own port (55414) for
its status, as a web user with the right status that the admin stores on the host (use
basic, user:password); until one is stored the check warns that it has none. Only counts and
ages leave the host, never a client name.

A client whose last file or image backup failed is critical (a kind that is turned off or not
supported is no failure), so is a server that stopped for lack of space or reports a broken
database; a last file backup older than 26 hours warns. Clients not seen for 24 hours are
shown, not rated: a laptop is often away.

Not verified against a running server: the protocol comes from the author's Python wrapper.
Not covered: the server in a container and another web port.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "urbackup",
    "name": "UrBackup server",
    "version": 1,
    "description": "UrBackup server: service, failed client backups, free space and age.",
    "detect": {"units": ["urbackupsrv.service"]},
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
            "key": "clients",
            "name": "Client backups",
            "sensor": "app",
            "target": {"kind": "unit", "port_hint": 55414, "scheme": "http"},
            "params": {"view": "urbackup_status"},
            "credential": {"slot": "default", "use": "basic"},
            "interval": 900,
            "fields": [
                "clients",
                "clients_file_failed",
                "clients_image_failed",
                "clients_unseen_24h",
                "file_backup_age_max_s",
                "nospc_fatal",
                "database_error",
            ],
            "rules": [
                {"field": "clients_file_failed", "op": "gt", "value": 0, "level": "critical"},
                {"field": "clients_image_failed", "op": "gt", "value": 0, "level": "critical"},
                {"field": "nospc_fatal", "op": "eq", "value": True, "level": "critical"},
                {"field": "database_error", "op": "eq", "value": True, "level": "critical"},
                {
                    "field": "file_backup_age_max_s",
                    "op": "gt",
                    "value": _DAY_AND_TWO_HOURS,
                    "level": "warning",
                },
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "clients", "field": "clients", "label": "Clients"},
        {"check_key": "clients", "field": "clients_file_failed", "label": "File backup failed"},
        {"check_key": "clients", "field": "clients_image_failed", "label": "Image backup failed"},
        {"check_key": "clients", "field": "file_backup_age_max_s", "label": "Oldest file backup s"},
    ],
}
