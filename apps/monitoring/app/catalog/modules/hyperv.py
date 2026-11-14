# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Hyper-V host (R-1246).

The Virtual Machine Management service vmms finds the module. The agent reads root\\virtualization\\v2
over WMI and reports counts and one age: the VMs and those running, those whose health is a
failure, the heartbeats lost, the replicas in warning and critical, and the checkpoints with
the age of the oldest. No VM name, no GUID leaves the host. An unhealthy VM or a critical
replica is critical, a lost heartbeat or a replica in warning a warning. The checkpoints are
shown, not alarmed: a host without one has no age to rate (R-1475). `Measure-VM` is never
called (it needs resource metering switched on first). Not verified on a Hyper-V host.
"""

MODULE = {
    "id": "hyperv",
    "name": "Hyper-V",
    "version": 1,
    "description": "Hyper-V: VM health, lost heartbeats, replication and checkpoints.",
    "detect": {"units": ["vmms.service"]},
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
            "key": "vms",
            "name": "Virtual machines",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "hyperv"},
            "interval": 300,
            "timeout_s": 30,
            "fields": [
                "vms",
                "vms_running",
                "vms_unhealthy",
                "heartbeat_lost",
                "replication_warning",
                "replication_critical",
                "checkpoints",
                "oldest_checkpoint_age_s",
            ],
            "rules": [
                {"field": "vms_unhealthy", "op": "gt", "value": 0, "level": "critical"},
                {"field": "replication_critical", "op": "gt", "value": 0, "level": "critical"},
                {"field": "heartbeat_lost", "op": "gt", "value": 0, "level": "warning"},
                {"field": "replication_warning", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "vms", "field": "vms_running", "label": "VMs running"},
        {"check_key": "vms", "field": "vms_unhealthy", "label": "VMs unhealthy"},
        {"check_key": "vms", "field": "checkpoints", "label": "Checkpoints"},
    ],
}
