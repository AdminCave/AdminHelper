# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DFS Replication (R-1246).

The service DFSR finds the module. The agent reads the replicated folders from WMI
(DfsrReplicatedFolderInfo) and counts the day's events 2213 (replication stopped after an
unclean shutdown, waiting for a manual resume) and 4012 (the member was offline longer than
allowed and no longer replicates). A folder in error and either event are critical; a folder
not yet in normal operation (initial sync, auto recovery) is shown. The resume command that
event 2213 names is never run. Not covered: the backlog against other members (it asks
foreign hosts). Not verified on a DFS-R member.
"""

MODULE = {
    "id": "dfsr",
    "name": "DFS Replication",
    "version": 1,
    "description": "DFS Replication: folders in error and stopped or expired members.",
    "detect": {"units": ["DFSR.service"]},
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
            "key": "folders",
            "name": "Replicated folders",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "dfsr"},
            "interval": 900,
            "timeout_s": 30,
            "fields": [
                "folders",
                "folders_error",
                "folders_not_normal",
                "stopped_events_24h",
                "offline_too_long_24h",
            ],
            "rules": [
                {"field": "folders_error", "op": "gt", "value": 0, "level": "critical"},
                {"field": "stopped_events_24h", "op": "gt", "value": 0, "level": "critical"},
                {"field": "offline_too_long_24h", "op": "gt", "value": 0, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "folders", "field": "folders", "label": "Folders"},
        {"check_key": "folders", "field": "folders_error", "label": "Folders in error"},
    ],
}
