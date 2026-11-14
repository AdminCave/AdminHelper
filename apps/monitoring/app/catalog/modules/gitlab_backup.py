# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The backups of a GitLab Omnibus installation: age and size of the newest (R-1233).

The module is found by GitLab's backup folder /var/opt/gitlab/backups or its package
gitlab-ce or gitlab-ee, and watches that folder (gitlab_rails['backup_path'] by default).

Once an hour the agent's file_age sensor reads the newest regular file in the folder, never its
name. No file in the folder warns, a newest file older than 26 hours warns, and one that is
more than half smaller than at the run before warns until the next run.

A GitLab backup holds neither gitlab-secrets.json nor gitlab.rb: without them a restore loses
two-factor logins, CI variables and runner tokens. Save /etc/gitlab yourself.

Not covered: another backup_path, and backups uploaded to object storage.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "gitlab_backup",
    "name": "GitLab backups",
    "version": 1,
    "description": (
        "GitLab backups: age and size of the newest. Save gitlab-secrets.json and gitlab.rb yourself."
    ),
    "detect": {
        "markers": [
            {
                "id": "gitlab_backup.dir",
                "paths": ["/var/opt/gitlab/backups"],
                "packages": ["gitlab-ce", "gitlab-ee"],
            }
        ]
    },
    # No unit: the marker alone finds the module, which makes one instance named after it.
    "instance": "unit",
    "checks": [
        {
            "key": "newest",
            "name": "Newest backup",
            "sensor": "file_age",
            "params": {"newest_in": "/var/opt/gitlab/backups"},
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
