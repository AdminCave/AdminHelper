# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The backups of GitLab in Docker, in the volume of GitLab's documentation (R-1233).

GitLab's Docker guide mounts $GITLAB_HOME/data, with GITLAB_HOME=/srv/gitlab, at
/var/opt/gitlab: the backups land in /srv/gitlab/data/backups on the host. That folder finds
the module and is watched.

Once an hour the agent's file_age sensor reads the newest regular file in the folder, never its
name. No file in the folder warns, a newest file older than 26 hours warns, and one that is
more than half smaller than at the run before warns until the next run.

A GitLab backup holds neither gitlab-secrets.json nor gitlab.rb: without them a restore loses
two-factor logins, CI variables and runner tokens. Save $GITLAB_HOME/config yourself.

Not covered: another GITLAB_HOME or a named volume; there the admin adds a file_age check with
newest_in on the folder.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "gitlab_backup_docker",
    "name": "GitLab backups (Docker)",
    "version": 1,
    "description": (
        "GitLab in Docker: age and size of the newest backup. Save gitlab-secrets.json and gitlab.rb yourself."
    ),
    "detect": {
        "markers": [{"id": "gitlab_backup_docker.dir", "paths": ["/srv/gitlab/data/backups"]}]
    },
    # No unit: the marker alone finds the module, which makes one instance named after it.
    "instance": "unit",
    "checks": [
        {
            "key": "newest",
            "name": "Newest backup",
            "sensor": "file_age",
            "params": {"newest_in": "/srv/gitlab/data/backups"},
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
