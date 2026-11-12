# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frigate NVR from its image ghcr.io/blakeblackshear/frigate (R-1241).

The image's HEALTHCHECK asks /api/version every 15 s, so the container's health carries
Frigate's API. /api/stats answers with the stats Frigate's stats emitter last gathered and
costs no work of its own. The module asks it on the internal port 5000, which needs no
login and grants the admin role. The login on port 8971 is never asked: Frigate can rate
limit failed logins there and raises a notice for them. A networking.listen.internal bound
to 127.0.0.1 inside the container leaves port 5000 out of reach: the stats checks then
stay unknown, as the container listens on other ports only.

The stats give Frigate's version and uptime, the detections per second and the free space
of the recordings directory (MiB; Frigate deletes old recordings itself, so no rule). The
frames per second of all cameras together (camera_fps) exist from Frigate 0.17 on; below
that version the cameras check stays unknown. Under 0.1 frames per second no camera
delivers a picture: a warning. A single dead camera beside working ones is not found, as
the per-camera and per-detector stats are keyed by the names of the configuration.
"""

_STATS_TARGET = {"kind": "container", "port_hint": 5000, "scheme": "http"}

MODULE = {
    "id": "frigate",
    "name": "Frigate",
    "version": 1,
    "description": (
        "Frigate NVR: the container with its own health check, and the stats of the "
        "internal port: version, detections, free recording space and camera frames."
    ),
    "detect": {"container_images": ["ghcr.io/blakeblackshear/frigate"]},
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
            "key": "stats",
            "name": "Stats",
            "sensor": "http",
            "target": _STATS_TARGET,
            "params": {"path": "/api/stats"},
            "interval": 300,
            "fields": [
                "status_code",
                "data.service.version",
                "data.service.uptime",
                "data.detection_fps",
                "data.service.storage./media/frigate/recordings.free",
            ],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
        {
            "key": "cameras",
            "name": "Cameras",
            "sensor": "http",
            "target": _STATS_TARGET,
            "params": {"path": "/api/stats"},
            "interval": 300,
            "fields": ["data.camera_fps"],
            "rules": [{"field": "data.camera_fps", "op": "lt", "value": 0.1, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "stats", "field": "data.service.version", "label": "Version"},
        {"check_key": "cameras", "field": "data.camera_fps", "label": "Camera frames/s"},
        {"check_key": "stats", "field": "data.detection_fps", "label": "Detections/s"},
        {
            "check_key": "stats",
            "field": "data.service.storage./media/frigate/recordings.free",
            "label": "Free recording space (MiB)",
        },
    ],
}
