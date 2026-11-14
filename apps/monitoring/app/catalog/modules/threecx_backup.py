# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The backups of 3CX on Debian in its default folder: age and size of the newest (R-1233).

The module is found by the backup folder /var/lib/3cxpbx/Instance1/Data/Backups and watches it.

Once an hour the agent's file_age sensor reads the newest regular file in the folder, never its
name. No file in the folder warns, a newest file older than 26 hours warns, and one that is
more than half smaller than at the run before warns until the next run.

Not verified: the folder is 3CX's default as named in its documentation, not seen at an
installation. Not covered: a folder chosen in the management console and backups to remote
storage; there the admin adds a file_age check with newest_in on the folder.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "3cx_backup",
    "name": "3CX backups",
    "version": 1,
    "description": ("3CX: age and size of the newest backup in its default folder."),
    "detect": {
        "markers": [{"id": "3cx_backup.dir", "paths": ["/var/lib/3cxpbx/Instance1/Data/Backups"]}]
    },
    # No unit: the marker alone finds the module, which makes one instance named after it.
    "instance": "unit",
    "checks": [
        {
            "key": "newest",
            "name": "Newest backup",
            "sensor": "file_age",
            "params": {"newest_in": "/var/lib/3cxpbx/Instance1/Data/Backups"},
            "interval": 3600,
            "fields": ["exists", "age_s", "size_bytes"],
            "rules": [
                {"field": "exists", "op": "eq", "value": False, "level": "warning"},
                {"field": "age_s", "op": "gt", "value": _DAY_AND_TWO_HOURS, "level": "warning"},
                {"field": "size_bytes", "op": "drop_pct_gt", "value": 50, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "newest", "field": "age_s", "label": "Newest backup s"},
        {"check_key": "newest", "field": "size_bytes", "label": "Size bytes"},
    ],
}
