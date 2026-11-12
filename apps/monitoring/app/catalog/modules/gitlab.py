# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GitLab from the Omnibus image (gitlab/gitlab-ce, gitlab/gitlab-ee) or the Omnibus
package (R-1241).

The package runs every service under runit, started by gitlab-runsvdir.service; puma
listens on 127.0.0.1:8080 unless it serves TLS itself (puma['listen'], omnibus
libraries/puma.rb). /-/readiness?all=1 asks the database, Redis and Gitaly and answers 503
when one fails, /-/liveness only whether puma answers; both are exempt from Rack Attack
and answer only clients on the monitoring allowlist, by default 127.0.0.0/8 and ::1/128,
with a 404 page to any other. The checks ask puma on the unit's port 8080 from 127.0.0.1,
so the default allowlist lets them in and no redirect of nginx to HTTPS stands between.
They read only the status code: the 404 of a changed allowlist is no JSON. A 404 or
another answer below 500 is a warning (the allowlist), 5xx is critical.

The image gets no HTTP check: from the host the agent reaches only the container's nginx,
which redirects to HTTPS once the external URL is https (the agent follows no redirect to
another port) and sees the bridge address, which is not on the allowlist. Its own
HEALTHCHECK runs gitlab-healthcheck inside the container every 60 s, which asks /help over
nginx from localhost, so the container's health carries that answer.

Not covered here: `gitlab-ctl status` (a command, T15), the age of the backups (R-1233,
app backups), puma with its own TLS listener, and GitLab installed from source.
"""

_PUMA = {"kind": "unit", "port_hint": 8080, "scheme": "http"}


def _probe(key: str, name: str, path: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "http",
        "target": _PUMA,
        "params": {"path": path},
        "interval": 300,
        "fields": ["status_code"],
        "rules": [
            {"field": "status_code", "op": "ge", "value": 500, "level": "critical"},
            {"field": "status_code", "op": "ne", "value": 200, "level": "warning"},
        ],
    }


MODULE = {
    "id": "gitlab",
    "name": "GitLab",
    "version": 1,
    "description": (
        "GitLab from the Omnibus image or package: the container with the image's own "
        "health check, or the runit unit with puma's readiness (database, Redis, Gitaly) "
        "and liveness."
    ),
    "detect": {
        "container_images": ["gitlab/gitlab-ce", "gitlab/gitlab-ee"],
        "units": ["gitlab-runsvdir.service"],
    },
    "instance": "compose_project",
    "checks": [
        {
            "key": "container",
            "name": "Container",
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
            "key": "runsvdir",
            "name": "Runit unit",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        _probe("readiness", "Readiness", "/-/readiness?all=1"),
        _probe("liveness", "Liveness", "/-/liveness"),
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "runsvdir", "field": "active_state", "label": "Runit unit"},
        {"check_key": "readiness", "field": "status_code", "label": "Readiness"},
        {"check_key": "liveness", "field": "status_code", "label": "Liveness"},
    ],
}
