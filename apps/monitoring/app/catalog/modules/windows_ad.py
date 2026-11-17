# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Active Directory Domain Services on a domain controller (R-1245).

The service NTDS finds the module. Beside it the agent runs `repadmin /showrepl localhost /csv`
and reports only counts and an age: the inbound replication links, their partners, the links
failing now, those that never succeeded and the age of the oldest last success. No naming
context, no DC name, no error text leaves the host.

A last success older than 12 hours is critical (well beyond the default intersite schedule of 3
hours, within the tombstone lifetime by far); a failing link is a warning, since a single
failure heals with the next cycle. A single domain controller has no inbound link and so no age;
nothing to rate is ok (Kevin 2026-11-16, R-1475). Not covered: Netlogon, the KDC and W32Time (each its own
service), and `dcdiag`, which writes to the directory's logs. Not verified on a domain
controller: the CSV columns come from Microsoft's repadmin documentation.
"""

MODULE = {
    "id": "windows-ad",
    "name": "Active Directory",
    "version": 2,
    "description": "Active Directory: the NTDS service and the inbound replication of this DC.",
    "detect": {"units": ["NTDS.service"]},
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
            "key": "replication",
            "name": "Replication",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "ad_replication"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["partners", "links", "failing_links", "never_links", "oldest_success_age_s"],
            "rules": [
                {
                    "field": "oldest_success_age_s",
                    "op": "gt",
                    "value": 43200,
                    "level": "critical",
                    "if_absent": "ok",
                },
                {"field": "failing_links", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "replication", "field": "links", "label": "Replication links"},
        {"check_key": "replication", "field": "failing_links", "label": "Failing links"},
    ],
}
