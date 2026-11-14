# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Veeam Agent for Linux: the service and the outcome of its jobs (R-1233).

The module is found by veeamservice.service; a unit that is not active is critical. Once an
hour the agent's app sensor reads `veeamconfig session list` and keeps the newest finished
session of each job: how many jobs, how many of them failed or ended with a warning, how many
sessions run, and the age of the oldest last success. No job name leaves the host.

A job whose last session failed is critical, one that ended with a warning warns, and a last
success older than 26 hours warns.

Not verified: Veeam does not document the form of the session list; the agent reads the form it
assumes and reports any other as an error. Not covered: Veeam on Windows and jobs managed by a
Veeam Backup & Replication server.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "veeam",
    "name": "Veeam Agent for Linux",
    "version": 1,
    "description": "Veeam Agent for Linux: service, failed jobs and the oldest last success.",
    "detect": {"units": ["veeamservice.service"]},
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
            "key": "jobs",
            "name": "Jobs",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "veeam_sessions"},
            "interval": 3600,
            "fields": [
                "jobs",
                "jobs_failed",
                "jobs_warning",
                "sessions_running",
                "last_success_age_max_s",
            ],
            "rules": [
                {"field": "jobs_failed", "op": "gt", "value": 0, "level": "critical"},
                {"field": "jobs_warning", "op": "gt", "value": 0, "level": "warning"},
                {
                    "field": "last_success_age_max_s",
                    "op": "gt",
                    "value": _DAY_AND_TWO_HOURS,
                    "level": "warning",
                },
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "jobs", "field": "jobs", "label": "Jobs"},
        {"check_key": "jobs", "field": "jobs_failed", "label": "Jobs failed"},
        {"check_key": "jobs", "field": "last_success_age_max_s", "label": "Oldest success s"},
    ],
}
