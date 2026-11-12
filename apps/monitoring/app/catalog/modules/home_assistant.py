# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Home Assistant from its image or the one of linuxserver.io (R-1243).

The module asks GET / on 8123 without credentials. Home Assistant serves its frontend page from
a cached template; before its onboarding it redirects to /onboarding.html, a static page the
agent follows to. No request carries a token and none asks the API: each 401 makes Home
Assistant raise a notification in its frontend and, with login_attempts_threshold set, count
the address towards a ban. A 403 is the agent's address on the ban list (ip_bans.yaml), which
refuses every request from there; it is critical like anything but 200. The container usually
runs on the host's network (network_mode: host), as the installation guide shows it: the scan
then sees no ports, and the agent finds 8123 among the sockets of the container's processes.
The images have no HEALTHCHECK of their own.

Not covered: Home Assistant OS and Supervised (an image of their own per machine), Home
Assistant Core in a venv on the host, a server that serves HTTPS on 8123 itself
(ssl_certificate), and the state of integrations and add-ons, which needs a token.
"""

MODULE = {
    "id": "home-assistant",
    "name": "Home Assistant",
    "version": 1,
    "description": (
        "Home Assistant from its image or the one of linuxserver.io: the container and whether "
        "its frontend answers."
    ),
    "detect": {
        "container_images": [
            "ghcr.io/home-assistant/home-assistant",
            "homeassistant/home-assistant",
            "lscr.io/linuxserver/homeassistant",
            "ghcr.io/linuxserver/homeassistant",
            "linuxserver/homeassistant",
        ]
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
            "key": "frontend",
            "name": "Frontend",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8123, "scheme": "http"},
            "params": {"path": "/"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "frontend", "field": "status_code", "label": "Frontend"},
    ],
}
