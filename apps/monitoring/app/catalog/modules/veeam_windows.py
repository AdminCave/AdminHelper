# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Veeam Agent for Microsoft Windows (R-1436).

The service VeeamEndpointBackupSvc finds the module. The agent reads the newest event 190 (a
job ended) of the log "Veeam Agent" and reports its age and its result from the event's level:
information success, warning a warning, error a failure; no job name, no text. A failed run is
critical, a warning a warning, a last run older than 36 hours a warning. Before the first run
there is no result, and the check stays unknown. Not verified on a host with the Veeam Agent.
"""

MODULE = {
    "id": "veeam-windows",
    "name": "Veeam Agent (Windows)",
    "version": 1,
    "description": "Veeam Agent for Windows: result and age of the last backup job.",
    "detect": {"units": ["VeeamEndpointBackupSvc.service"]},
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
            "key": "job",
            "name": "Last job",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "veeam_windows"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["runs", "last_result", "last_run_age_s"],
            "rules": [
                {"field": "last_result", "op": "eq", "value": "failed", "level": "critical"},
                {"field": "last_result", "op": "eq", "value": "warning", "level": "warning"},
                {"field": "last_run_age_s", "op": "gt", "value": 129600, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "job", "field": "last_result", "label": "Last result"},
        {"check_key": "job", "field": "last_run_age_s", "label": "Last run"},
    ],
}
