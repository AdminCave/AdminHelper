# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Windows print spooler (R-1246).

The service Spooler finds the module while it runs: on a domain controller the spooler is
switched off on purpose, and a stopped one makes no instance. The agent reads the printers
and print jobs from WMI and reports how many printers cannot print (out of paper or toner,
jammed, offline, door open) and how many jobs are in error, with the age of the oldest job;
no printer or document name. Either is a warning. Not verified on a print server.
"""

MODULE = {
    "id": "print-server",
    "name": "Print server",
    "version": 1,
    "description": "Windows print spooler: printers in error and stuck print jobs.",
    "detect": {"units": ["Spooler.service"]},
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
            "key": "queues",
            "name": "Printers and jobs",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "print"},
            "interval": 300,
            "timeout_s": 30,
            "fields": ["printers", "printers_error", "jobs", "jobs_error", "oldest_job_age_s"],
            "rules": [
                {"field": "printers_error", "op": "gt", "value": 0, "level": "warning"},
                {"field": "jobs_error", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "queues", "field": "printers_error", "label": "Printers in error"},
        {"check_key": "queues", "field": "jobs_error", "label": "Jobs in error"},
    ],
}
