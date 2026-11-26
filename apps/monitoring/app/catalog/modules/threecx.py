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

The certificate of the web interface, which 3CX serves through the system's nginx on 443
(a new install) or 5001 (after an upgrade), is checked once per host: at the instance of
the management console only (R-1443), on the first of the two ports the last scan saw
listening outside a container. A port chosen freely at setup leaves the check unbound.

Not covered: the age of the backups (module 3cx_backup).
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
    "version": 2,
    "description": (
        "3CX Phone System on Debian: each service of the package, from the SIP server "
        "to the media server, as a unit of its own, and the certificate of its web interface."
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
        {
            "key": "web_certificate",
            "name": "Web interface certificate",
            "sensor": "tls",
            "instance": "3CXPhoneSystemMC01.service",
            "target": {
                "kind": "loopback",
                "alternatives": [
                    {"port_hint": 443, "scheme": "https"},
                    {"port_hint": 5001, "scheme": "https"},
                ],
            },
            "interval": 3600,
            "fields": ["days_left", "not_after", "issuer", "chain_ok"],
            "rules": [
                {"field": "days_left", "op": "lt", "value": 22, "level": "warning"},
                {"field": "days_left", "op": "lt", "value": 9, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service", "field": "sub_state", "label": "State"},
        {
            "check_key": "web_certificate",
            "field": "days_left",
            "label": "Web certificate days left",
        },
    ],
}
