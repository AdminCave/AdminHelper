# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BigBlueButton from the unit of its API server bbb-web (R-1242).

bbb-web (BigBlueButton 3.0 and 4.0) runs as bbb-web.service and listens on LISTEN_ADDRESS
and LISTEN_PORT from /etc/default/bbb-web, 127.0.0.1:8090 by default; the system's nginx
passes /bigbluebutton to it. GET /bigbluebutton/api reaches ApiController.index, which
answers SUCCESS and the version without a checksum, without a login and without touching a
meeting; the check reads the status code only.

The other units of the installation (graphql server, webrtc SFU, recorder, livekit,
coturn, ...) are left to the service health of linux-base: a unit instance each would bind
the API check to every one of them. Not covered: the certificate (nginx serves it for a
host name the module does not know), getMeetings (it needs a checksum from the secret),
the *.fail files of the recording processing and bbb-conf --check. bbb-conf with
--restart, --clean or --setip and bbb-record with --rebuild or --delete are never run.
"""

MODULE = {
    "id": "bigbluebutton",
    "name": "BigBlueButton",
    "version": 1,
    "description": (
        "BigBlueButton: the API server bbb-web as a unit and its API, which answers "
        "without a checksum."
    ),
    "detect": {"units": ["bbb-web.service"]},
    "instance": "unit",
    "checks": [
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
            "key": "api",
            "name": "API",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8090, "scheme": "http"},
            "params": {"path": "/bigbluebutton/api"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "api", "field": "status_code", "label": "API"},
    ],
}
