# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The local IPMI sensors of the host's BMC, read through the agent's host sensor (R-1228).

The agent asks ipmitool for the sensor list from a cache of the sensor records it refreshes
daily, only over the local IPMI device and never over the network (no Redfish): how many
sensors report, how many are in a critical or non-recoverable state and how many in a
non-critical one. The system event log is not read (sel elist loads the BMC).
"""

MODULE = {
    "id": "ipmi",
    "name": "IPMI sensors",
    "version": 1,
    "description": "The BMC's sensors over the local IPMI device: critical and warning states.",
    # The device node of the kernel's IPMI driver; without ipmitool the view is unsupported.
    "detect": {
        "markers": [
            {
                "id": "ipmi.device",
                "paths": ["/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0"],
            }
        ],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "sensors",
            "name": "Sensors",
            "sensor": "host",
            "params": {"view": "ipmi_sensors"},
            "interval": 900,
            # The cache dump and the sensor list, up to 14 s each.
            "timeout_s": 30,
            "fields": ["sensors", "critical", "noncritical"],
            "rules": [
                {"field": "critical", "op": "gt", "value": 0, "level": "critical"},
                {"field": "noncritical", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "sensors", "field": "sensors", "label": "Sensors"},
        {"check_key": "sensors", "field": "critical", "label": "Critical"},
        {"check_key": "sensors", "field": "noncritical", "label": "Warning"},
    ],
}
