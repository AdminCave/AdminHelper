# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""linuxmuster.net 7.x from the unit of its web UI (R-1240).

The module is found by linuxmuster-webui.service (linuxmuster-webui7). Every 15 minutes the
agent's app sensor compares, for the school default-school, the modification time of
devices.csv with that of the DHCP file the last device import wrote: a list newer than its
import warns (the import is pending). Whether the last run of import-devices.log completed and
its errors are shown, not rated: older base7 writes no start of a run there, and a rule on a
missing field would hold the check at unknown.
Every hour it counts the LINBO images under /srv/linbo/images whose .torrent is older than the
image, which warns: clients would fetch the old image. Once a day the agent reads the server
certificate /etc/linuxmuster/ssl/server.cert.pem (the name from linuxmuster-base7 certs.py,
the directory SSLDIR of its environment module): fewer than 30 days left warn, fewer than 7 are
critical. Neither the device list nor an image name leaves the host; linbo-torrent status and
sophomorix-check are never run.

Not covered: other schools than default-school, the units linbo-multicast and linbo-torrent
(oneshots with RemainAfterExit: active says nothing about their tmux sessions), tftpd-hpa and
rsync, linuxmuster-api on 8001 (every path needs a token), the Sophomorix backlog and the
OPNsense of the school. Samba AD and the DHCP server are the modules samba-ad-dc and
isc-dhcp-server.
"""

MODULE = {
    "id": "linuxmuster",
    "name": "linuxmuster.net",
    "version": 1,
    "description": (
        "linuxmuster.net 7.x: the web UI's unit, the device import, the torrents of the LINBO "
        "images and the server certificate."
    ),
    "detect": {"units": ["linuxmuster-webui.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Web UI",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "devices",
            "name": "Device import",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "lmn_devices"},
            "interval": 900,
            "fields": ["import_pending", "last_import_age_s", "import_completed", "import_errors"],
            "rules": [
                {"field": "import_pending", "op": "eq", "value": True, "level": "warning"},
            ],
        },
        {
            "key": "linbo",
            "name": "LINBO images",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "lmn_linbo"},
            "interval": 3600,
            "fields": ["images", "torrents_stale"],
            "rules": [{"field": "torrents_stale", "op": "gt", "value": 0, "level": "warning"}],
        },
        {
            "key": "certificate",
            "name": "Server certificate",
            "sensor": "certfile",
            "params": {"path": "/etc/linuxmuster/ssl/server.cert.pem"},
            "interval": 86400,
            "fields": ["days_left", "not_after", "issuer"],
            "rules": [
                {"field": "days_left", "op": "lt", "value": 30, "level": "warning"},
                {"field": "days_left", "op": "lt", "value": 7, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Web UI"},
        {"check_key": "devices", "field": "import_pending", "label": "Import pending"},
        {"check_key": "linbo", "field": "images", "label": "LINBO images"},
        {"check_key": "linbo", "field": "torrents_stale", "label": "Stale torrents"},
        {"check_key": "certificate", "field": "days_left", "label": "Certificate days left"},
    ],
}
