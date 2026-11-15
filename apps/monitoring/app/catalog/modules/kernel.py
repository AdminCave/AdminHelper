# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The running kernel: taint bits of a crash or failing hardware and stuck live patches (R-1234).

The agent's host sensor reads /proc/sys/kernel/tainted and the transition files under
/sys/kernel/livepatch, both only opened for reading (Konzept §6.14). The bits D (the kernel died:
OOPS or BUG), M (a machine check exception) and B (a bad page) are critical: they stay set until
the next boot and point at a crashed kernel or failing hardware. A live patch still in transition
warns. The raw taint is shown: a proprietary or out-of-tree module taints too and harms nothing.
"""

MODULE = {
    "id": "kernel",
    "name": "Linux kernel",
    "version": 1,
    "description": "Linux kernel: an OOPS, a machine check or a bad page, and stuck live patches.",
    "detect": {
        "markers": [{"id": "kernel.tainted", "paths": ["/proc/sys/kernel/tainted"]}],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "taint",
            "name": "Kernel taint",
            "sensor": "host",
            "params": {"view": "kernel_taint"},
            "interval": 300,
            "fields": ["tainted", "oops", "mce", "bad_page", "livepatch_transition"],
            "rules": [
                {"field": "oops", "op": "eq", "value": True, "level": "critical"},
                {"field": "mce", "op": "eq", "value": True, "level": "critical"},
                {"field": "bad_page", "op": "eq", "value": True, "level": "critical"},
                {"field": "livepatch_transition", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "taint", "field": "tainted", "label": "Taint"},
        {
            "check_key": "taint",
            "field": "livepatch_transition",
            "label": "Live patches in transition",
        },
    ],
}
