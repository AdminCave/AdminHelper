# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frps container of an AdminHelper server (R-1375).

frps speaks only its own protocol on the bind port and routes its vhost port by SNI, so
a port check with protocol auto learns nothing there and frps logs every try. Claiming
the container keeps its ports out of the module port; the check asks the container.
"""

MODULE = {
    "id": "frps",
    "name": "FRP server",
    "version": 1,
    "description": (
        "The frps container that carries the FRP tunnels of AdminHelper. Its ports are "
        "not watched as listening ports; the check asks whether the container runs."
    ),
    "detect": {
        "container_images": ["ghcr.io/admincave/adminhelper/frps", "snowdreamtech/frps"],
    },
    "instance": "container",
    "checks": [
        {
            "key": "running",
            "name": "Container runs",
            "sensor": "container",
            "target": {"kind": "container"},
            "params": {},
            "interval": 300,
            "fields": ["state", "health", "restarts"],
            "rules": [{"field": "state", "op": "ne", "value": "running", "level": "critical"}],
        }
    ],
    "card": [
        {"check_key": "running", "field": "state", "label": "State"},
        {"check_key": "running", "field": "restarts", "label": "Restarts"},
    ],
}
