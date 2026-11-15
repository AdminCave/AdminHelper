# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""needrestart: a kernel, microcode or library update that waits for a restart (R-1234).

The agent's host sensor runs `needrestart -b` once an hour: batch mode never restarts anything
nor shows a dialog (README.batch). It reports the kernel status (NEEDRESTART-KSTA: 0 unknown,
1 current, 2 an ABI-compatible upgrade pending, 3 a version upgrade pending), the microcode status
(NEEDRESTART-UCSTA: 0 unknown, 1 current, 2 obsolete) and how many services still run with replaced
libraries. A pending kernel or an obsolete microcode warns, as does any such service. No service
name leaves the host.
"""

MODULE = {
    "id": "needrestart",
    "name": "needrestart",
    "version": 1,
    "description": "needrestart: a pending kernel or microcode and services on old libraries.",
    "detect": {
        "markers": [
            {
                "id": "needrestart.bin",
                "paths": ["/usr/sbin/needrestart"],
                "packages": ["needrestart"],
            }
        ],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "restart",
            "name": "Pending restarts",
            "sensor": "host",
            "params": {"view": "needrestart"},
            "interval": 3600,
            # needrestart reads the maps of every process; the agent gives it these 30 s, the most a
            # probe may take.
            "timeout_s": 30,
            "fields": ["kernel_status", "microcode_status", "services"],
            "rules": [
                {"field": "kernel_status", "op": "ge", "value": 2, "level": "warning"},
                {"field": "microcode_status", "op": "ge", "value": 2, "level": "warning"},
                {"field": "services", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "restart", "field": "kernel_status", "label": "Kernel status"},
        {"check_key": "restart", "field": "services", "label": "Services"},
    ],
}
