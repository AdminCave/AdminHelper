# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UniFi OS Server, found by its unit uosserver (R-1244, the local part).

The UniFi OS Server runs the UniFi Network application in a Podman container under the unit
uosserver and serves it on HTTPS port 11443. The unit not active is critical; the certificate
of that port warns three weeks before it runs out.

Every five minutes the agent's app sensor reads the view unifi_network: it asks the local
Integration API of the Network application (/proxy/network/integration/v1, OpenAPI of the
application 11.0.97 from developer.ui.com) with the key in header X-API-KEY, only by GET, only
on a list of read paths, without following a redirect, at most 20 requests per run, and sends
the key only to the port the unit or the rootless Podman of its user holds. The key has no
scopes, inherits the rights of the admin who creates it and needs one with full Network
management: an admin with View Only cannot open the integrations, so no read-only key exists,
and the key could restart, power-cycle or reset devices, which is why the agent's client allows
nothing but those reads. The key is kept on the host (credential slot default); the server only
knows that one is set. Tested against UniFi OS Server 5.1.42 with Network 10.5.67.

The view sends counts only: sites, devices, devices offline, offline_root (offline devices
whose uplink is not itself offline: the cause, not what hangs behind it), gateways offline,
devices updating, devices with a firmware update, devices waiting for adoption and clients. A
gateway offline is critical, a cause offline warns. No name, MAC or address of a device or a
client leaves the host.

Not covered: the list of devices with names (R-1518), the Site Manager (R-1518), PoE and port
speed, statistics per device, a delay for devices updating or adopting (counted, no rule),
UniFi OS consoles (UDM, UCG, Cloud Key) and the old UniFi Network Server.
"""

MODULE = {
    "id": "unifi-os-server",
    "name": "UniFi OS Server",
    "version": 1,
    "description": (
        "UniFi OS Server: the service, the certificate of its web port and the state of the "
        "devices its UniFi Network application manages, as counts."
    ),
    # pasta holds 11443 outside the unit's cgroup: the hint claims it, or it stays a port finding.
    "detect": {"units": ["uosserver.service"], "port_hints": [11443]},
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
            "key": "certificate",
            "name": "Web certificate",
            "sensor": "tls",
            # Rootless Podman's port forwarder holds 11443 outside the unit's cgroup, so the
            # unit rule finds no port; the check needs no key and reads it on loopback.
            "target": {"kind": "loopback", "port_hint": 11443},
            "interval": 3600,
            "fields": ["days_left", "not_after", "issuer", "chain_ok"],
            "rules": [
                {"field": "days_left", "op": "lt", "value": 22, "level": "warning"},
                {"field": "days_left", "op": "lt", "value": 9, "level": "critical"},
            ],
        },
        {
            "key": "network",
            "name": "Network devices",
            "sensor": "app",
            "target": {"kind": "unit", "port_hint": 11443},
            "params": {"view": "unifi_network"},
            "interval": 300,
            "timeout_s": 30,
            "credential": {"slot": "default", "use": "header:X-API-KEY"},
            "fields": [
                "sites",
                "devices",
                "offline",
                "offline_root",
                "gateways_offline",
                "updating",
                "firmware_updatable",
                "pending",
                "clients",
            ],
            "rules": [
                {"field": "gateways_offline", "op": "gt", "value": 0, "level": "critical"},
                {"field": "offline_root", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "network", "field": "offline", "label": "Devices offline"},
        {"check_key": "network", "field": "firmware_updatable", "label": "Firmware updates"},
    ],
}
