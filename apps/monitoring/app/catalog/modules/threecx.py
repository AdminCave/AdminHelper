# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""3CX Phone System on Debian, from the units of its package 3cxpbx (R-1241).

The unit names come from the package 3cxpbx 20.0 of 3CX's apt repository. Its
3CXStartServices enables and starts the services 3cxpbx.conf lists (SIP server,
configuration service, management console, media server, IVR, queue manager, call flow,
system server, audio provider, hotel module, AI bridge, gateway, event notification);
3CXFirewall is a oneshot unit that stays active after it ran. Each unit is an instance of
its own, so the alert names the failed service; a unit that is installed but inactive
makes no instance, a failed one stays watched.

Not covered: the certificate of the web interface, which 3CX serves through the system's
nginx on 443 or 5001 (or another port chosen at setup), and the age of the backups, which
land in a folder chosen in the management console or on remote storage.
"""

_UNITS = [
    "3CXPhoneSystem01.service",
    "3CXCfgServ01.service",
    "3CXPhoneSystemMC01.service",
    "3CXMediaServer.service",
    "3CXIVR01.service",
    "3CXQueueManager01.service",
    "3CXCallFlow01.service",
    "3CXSystemService01.service",
    "3CXAudioProvider01.service",
    "3CXHotelModule01.service",
    "3CXAI.service",
    "3CXGatewayService.service",
    "3CXEventNotificationManager.service",
    "3CXFirewall.service",
]

MODULE = {
    "id": "3cx",
    "name": "3CX",
    "version": 1,
    "description": (
        "3CX Phone System on Debian: each service of the package, from the SIP server "
        "to the media server, as a unit of its own."
    ),
    "detect": {"units": _UNITS},
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
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service", "field": "sub_state", "label": "State"},
    ],
}
