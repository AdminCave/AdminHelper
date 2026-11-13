# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BigBlueButton from the unit of its API server bbb-web (R-1242, R-1404).

bbb-web (BigBlueButton 3.0 and 4.0) runs as bbb-web.service and listens on LISTEN_ADDRESS
and LISTEN_PORT from /etc/default/bbb-web, 127.0.0.1:8090 by default; the system's nginx
passes /bigbluebutton to it. GET /bigbluebutton/api reaches ApiController.index, which
answers SUCCESS and the version without a checksum, without a login and without touching a
meeting; the check reads the status code only.

The agent's app sensor (R-1404) adds two reads. Every five minutes the view bbb_meetings
asks getMeetings on the port of bbb-web.service with the checksum it computes from the
securitySalt of the host's bbb-web.properties (/etc/bigbluebutton first, then the packaged
file, as bbb-conf reads them); the secret leaves the agent only as that checksum, sent to
bbb-web's own port. Of the answer it counts meetings, running and recording ones,
participants, listeners, voice and video users; it never reads or reports a meeting's name,
a password, an attendee or metadata. Every 15 minutes the view bbb_recordings counts the
markers *.fail the recording processing leaves per step under
/var/bigbluebutton/recording/status, by name and without reading one, and the age of the
newest; any failed recording warns.

The other units of the installation (graphql server, webrtc SFU, recorder, livekit,
coturn, ...) are left to the service health of linux-base: a unit instance each would bind
the API check to every one of them. Not covered: the certificate (nginx serves it for a
host name the module does not know) and bbb-conf --check, which is never run: as root it
writes and deletes /tmp/t, asks an external STUN server and searches all logs of the
installation. bbb-conf with --restart, --clean or --setip and bbb-record with --rebuild or
--delete are never run either.
"""

MODULE = {
    "id": "bigbluebutton",
    "name": "BigBlueButton",
    "version": 2,
    "description": (
        "BigBlueButton: the API server bbb-web as a unit and its API, which answers "
        "without a checksum; the meetings and participants on the server and the recordings "
        "whose processing failed."
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
        {
            "key": "meetings",
            "name": "Meetings",
            "sensor": "app",
            # The view sends its checksum only to the port of bbb-web.service.
            "target": {"kind": "unit", "port_hint": 8090},
            "params": {"view": "bbb_meetings"},
            "interval": 300,
            "fields": [
                "meetings",
                "running",
                "participants",
                "listeners",
                "voice",
                "video",
                "recording",
            ],
        },
        {
            "key": "recordings",
            "name": "Recordings",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "bbb_recordings"},
            "interval": 900,
            "fields": [
                "failed",
                "archive_failed",
                "sanity_failed",
                "process_failed",
                "publish_failed",
                "newest_fail_age_s",
            ],
            "rules": [{"field": "failed", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "api", "field": "status_code", "label": "API"},
        {"check_key": "meetings", "field": "meetings", "label": "Meetings"},
        {"check_key": "meetings", "field": "participants", "label": "Participants"},
        {"check_key": "recordings", "field": "failed", "label": "Failed recordings"},
    ],
}
