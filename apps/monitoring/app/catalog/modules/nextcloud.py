# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Nextcloud from the official Docker image or the snap (R-1241).

status.php is public and cheap: it reads the config and the version and answers JSON
(installed, maintenance, needsDbUpgrade, versionstring, …), with 200 in maintenance mode
too, since only index.php runs the 503 maintenance page (lib/OC.php handleRequest). It
answers 400 to a host name the instance does not trust, and localhost is always trusted
(TrustedDomainHelper), so the check sends Host: localhost.

The checks bind to the compose services `app` and `cron` of the image's README and example
compose. Both containers are watched, since status.php does not see a dead cron container
(background jobs stop); a project without a cron service leaves that check unbound. The
HTTP check asks only `app`: the cron container has no web server, and the fpm image speaks
FastCGI on 9000, so probe_config binds no HTTP check to a container without the hinted
port 80. A container started without compose, or whose app service has another name,
gets the app and status checks too: they fall back to the one container of the instance
with the image that is not the cron service (image_fallback). The cron check keeps its
service, since a lone container cannot tell its job. The snap runs its web server as snap.nextcloud.apache.service, whose state is
watched; its HTTP answer redirects to HTTPS once that is on, so it gets no HTTP check.

Not covered here: the All-in-One images (nextcloud/aio-*; their backup stops the
containers, port and TLS of the web server are the admin's), a cron container under
another service name, a package install behind the host's web server
(R-1231), and the serverinfo app (a costly answer from the database and the file system).
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]


def _container(key: str, name: str, image_fallback: bool) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "container",
        "target": {"kind": "container", "service": key, "image_fallback": image_fallback},
        "interval": 300,
        "fields": ["state", "health", "restarts"],
        "rules": _CONTAINER_RULES,
    }


MODULE = {
    "id": "nextcloud",
    "name": "Nextcloud",
    "version": 2,
    "description": (
        "Nextcloud from the official Docker image or the snap: the app and cron containers, "
        "status.php for maintenance mode and a pending database upgrade, the snap's web "
        "server unit."
    ),
    "detect": {
        "container_images": ["nextcloud"],
        # One unit only: a check bound through the stand-in instance needs an unambiguous one.
        "units": ["snap.nextcloud.apache.service"],
    },
    "instance": "compose_project",
    "checks": [
        _container("app", "App container", image_fallback=True),
        _container("cron", "Cron container", image_fallback=False),
        {
            "key": "status",
            "name": "Status",
            "sensor": "http",
            "target": {
                "kind": "container",
                "service": "app",
                "image_fallback": True,
                "port_hint": 80,
                "scheme": "http",
            },
            "params": {"path": "/status.php", "host": "localhost"},
            "interval": 300,
            "fields": [
                "status_code",
                "data.installed",
                "data.maintenance",
                "data.needsDbUpgrade",
                "data.versionstring",
            ],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "data.maintenance", "op": "eq", "value": True, "level": "warning"},
                {"field": "data.needsDbUpgrade", "op": "eq", "value": True, "level": "warning"},
            ],
        },
        {
            "key": "snap",
            "name": "Snap web server",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
    ],
    "card": [
        {"check_key": "status", "field": "data.versionstring", "label": "Version"},
        {"check_key": "status", "field": "data.maintenance", "label": "Maintenance mode"},
        {"check_key": "status", "field": "data.needsDbUpgrade", "label": "Database upgrade due"},
        {"check_key": "app", "field": "state", "label": "App container"},
        {"check_key": "cron", "field": "state", "label": "Cron container"},
        {"check_key": "snap", "field": "active_state", "label": "Snap web server"},
    ],
}
