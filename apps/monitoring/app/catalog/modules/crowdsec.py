# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CrowdSec's security engine from its package or from the image crowdsecurity/crowdsec
(R-1236).

For the package the agent's app sensor reads `cscli bouncers list -o json` every five
minutes and reports how many bouncers are registered and not revoked, how many have not
pulled decisions for more than 10 minutes, and the oldest pull; never a bouncer's name, key
or address, and it adds or deletes no decision. A stale bouncer warns: it may no longer
block what the engine decides. The rule warns rather than alarms because CrowdSec's local
API renews a bouncer's last pull only when it asks: a bouncer in stream mode with each
poll, one in live mode with the requests it filters (at most once a minute), so a live
bouncer on a quiet host goes stale without a fault. Turn the rule off there.

The image gets its container check; cscli inside the container is not asked. Not covered:
the acquisition sources, parsers and scenarios, and the central API.
"""

MODULE = {
    "id": "crowdsec",
    "name": "CrowdSec",
    "version": 1,
    "description": (
        "CrowdSec from its package or image: the unit or the container, and for the package "
        "whether its bouncers still pull decisions."
    ),
    "detect": {
        "container_images": ["crowdsecurity/crowdsec"],
        "units": ["crowdsec.service"],
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
            "key": "service",
            "name": "Service",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "bouncers",
            "name": "Bouncers",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "crowdsec_bouncers"},
            "interval": 300,
            "fields": ["bouncers", "stale_bouncers", "max_pull_age_s"],
            "rules": [{"field": "stale_bouncers", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "bouncers", "field": "stale_bouncers", "label": "Stale bouncers"},
    ],
}
