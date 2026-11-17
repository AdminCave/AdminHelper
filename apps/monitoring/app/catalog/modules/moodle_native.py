# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moodle installed on the host, behind its nginx or Apache (R-1378, R-1422).

The agent tells the vhost of a Moodle by its document root (admin/cli/checks.php and
lib/moodlelib.php there); the vhost's domain is the instance. Every 5 minutes the agent asks
the front page at the vhost's port by the vhost's name. It follows no redirect to another host
name (it connects to 127.0.0.1), so a site that forces a login (forcelogin) stays unknown here.
The login page itself is not asked and neither is /admin/cron.php (it starts the cron, concept
§6.10).

Every 15 minutes the agent runs admin/cli/checks.php of the document root as the web server's
user (moodle_checks): the status checks of the site (database, cron, caches …). It reports the
state (ok, warning, critical, unknown from the exit code) and the number of checks that are not
OK, never their text. It runs only code that belongs to root and that user and that no one
else may write, below the dataroot too; a Moodle whose directories anyone may write (the
default directorypermissions 02777) or whose dataroot belongs to another user stays unknown.

Every 15 minutes the agent reads how full the file system of the dataroot (moodledata) is
(moodle_data, R-1504): the dataroot of config.php, read without running code, of it only statfs as
the sensor fs does. From 80 % used a warning, from 90 % critical, inodes from 90 % a warning.
"""

MODULE = {
    "id": "moodle_native",
    "name": "Moodle (host)",
    "version": 2,
    "description": (
        "Moodle installed on the host behind its web server: whether the site answers, and "
        "the state of its own status checks, and how full its moodledata is."
    ),
    "detect": {"vhost_apps": ["moodle"]},
    "instance": "vhost",
    "checks": [
        {
            "key": "site",
            "name": "Site",
            "sensor": "http",
            "target": {"kind": "vhost"},
            "params": {"path": "/"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
        {
            "key": "checks",
            "name": "Status checks",
            "sensor": "app",
            "target": {"kind": "vhost"},
            "params": {"view": "moodle_checks"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["state", "not_ok"],
            "rules": [
                {"field": "state", "op": "eq", "value": "critical", "level": "critical"},
                {"field": "state", "op": "eq", "value": "warning", "level": "warning"},
            ],
        },
        {
            "key": "data",
            "name": "moodledata",
            "sensor": "app",
            "target": {"kind": "vhost"},
            "params": {"view": "moodle_data"},
            "interval": 900,
            "fields": ["used_pct", "free_bytes", "inodes_used_pct"],
            "rules": [
                {"field": "used_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "used_pct", "op": "ge", "value": 90, "level": "critical"},
                {"field": "inodes_used_pct", "op": "ge", "value": 90, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "site", "field": "status_code", "label": "Site"},
        {"check_key": "checks", "field": "state", "label": "Status checks"},
        {"check_key": "checks", "field": "not_ok", "label": "Checks not OK"},
        {"check_key": "data", "field": "used_pct", "label": "moodledata %"},
    ],
}
