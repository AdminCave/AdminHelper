# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Nextcloud All-in-One, found by the image of its mastercontainer (R-1383).

AIO runs its containers under fixed names nextcloud-aio-* (php/containers.json); those it
keeps running have the restart policy unless-stopped, while borgbackup, watchtower and
domaincheck run for a while and have none. The nightly backup (daily-backup.sh of the
mastercontainer) creates /mnt/docker-aio-config/data/daily_backup_running before it stops the
containers and removes it once they run again; a backup started from the interface runs the
container nextcloud-aio-borgbackup without the file. A check per container would therefore
alarm every night.

So every five minutes the agent's app sensor reads the view nextcloud_aio at the
mastercontainer: it stats the marker below the container's root without reading it and
counts the containers of AIO with unless-stopped beside the mastercontainer. It sends only
containers, stopped (those of them not running, 0 while a backup runs), backup and
backup_age_s (the age of the marker, 0 without one); no name and no path leaves the host. A
stopped container outside a backup is critical, a backup running for more than six hours
warns. configuration.json of the mastercontainer carries passwords and is never read.

Not covered: status.php of the apache container (stopped in every backup window; a rule
cannot look at the field of another check), port and TLS of the web server (APACHE_PORT is
the admin's), which container stands (the host's container list shows it), and AIO on
Windows or under another container runtime.
"""

MODULE = {
    "id": "nextcloud-aio",
    "name": "Nextcloud All-in-One",
    "version": 1,
    "description": (
        "Nextcloud All-in-One: the mastercontainer and whether the containers it keeps "
        "running run, without an alarm while its backup stops them."
    ),
    "detect": {
        "container_images": ["ghcr.io/nextcloud-releases/all-in-one", "nextcloud/all-in-one"]
    },
    "instance": "container",
    "checks": [
        {
            "key": "master",
            "name": "Mastercontainer",
            "sensor": "container",
            "target": {"kind": "container"},
            "interval": 300,
            "fields": ["state", "health", "restarts"],
            "rules": [
                {"field": "state", "op": "ne", "value": "running", "level": "critical"},
                {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
            ],
        },
        {
            "key": "aio",
            "name": "Containers",
            "sensor": "app",
            "target": {"kind": "container"},
            "params": {"view": "nextcloud_aio"},
            "interval": 300,
            "fields": ["containers", "stopped", "backup", "backup_age_s"],
            "rules": [
                {"field": "stopped", "op": "gt", "value": 0, "level": "critical"},
                {"field": "backup_age_s", "op": "gt", "value": 21600, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "master", "field": "state", "label": "Mastercontainer"},
        {"check_key": "aio", "field": "stopped", "label": "Stopped containers"},
        {"check_key": "aio", "field": "backup", "label": "Backup running"},
    ],
}
