# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A network share this host mounts: nfs, nfs4, cifs or smb3 (R-1267).

The agent reads the mount table and reports each share by its mount point and type; where it
comes from (the server, the export) stays on the host (Kevin 2026-11-18). The disk list leaves
network shares out on Linux, so a share that hangs no longer holds up the agent's run: this
module checks it instead, every 5 minutes, with statfs in a process of its own that a 10 s
timeout ends. A share that does not answer in time or is no longer mounted is critical; its
fill is rated like a local disk, a warning from 85 %, critical from 95 % (Kevin 2026-11-18).

The probe's own timeout is above the 10 s of statfs, so a share that hangs reads as hung and
not as a probe that ran out of time. Linux only: on FreeBSD and Windows a share stays a disk.
"""

MODULE = {
    "id": "net_share",
    "name": "Network share",
    "version": 1,
    "description": (
        "A network share (NFS, SMB) this host mounts: whether it is still mounted, whether it "
        "answers, and how full it is."
    ),
    "detect": {"net_shares": True},
    "instance": "share",
    "checks": [
        {
            "key": "usage",
            "name": "Share mounted and fill",
            "sensor": "app",
            "target": {"kind": "share"},
            "params": {"view": "net_share_usage"},
            "interval": 300,
            "timeout_s": 20,
            "fields": ["mounted", "hung", "used_percent", "free_gb"],
            "rules": [
                {"field": "mounted", "op": "eq", "value": False, "level": "critical"},
                {"field": "hung", "op": "eq", "value": True, "level": "critical"},
                {"field": "used_percent", "op": "ge", "value": 85, "level": "warning"},
                {"field": "used_percent", "op": "ge", "value": 95, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "usage", "field": "used_percent", "label": "Used %"},
        {"check_key": "usage", "field": "free_gb", "label": "Free GB"},
        {"check_key": "usage", "field": "hung", "label": "Hangs"},
    ],
}
