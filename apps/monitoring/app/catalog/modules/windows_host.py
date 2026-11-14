# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A Windows host (R-1245): its updates, its critical and error events, its machine certificates.

The Windows Event Log service runs on every Windows, so it finds the module on each Windows
host with an agent. The agent asks the Windows Update Agent for the open updates of its last
offline search (it starts no online search: that would load the update servers; wuaRead
searches offline itself), counts the
critical and error events of the System and Application logs since its last run, and reads
the not-after dates of the certificates in LocalMachine\\My. Only counts, ages and booleans
leave the host, never an update's title, an event text or a certificate's subject.

A pending reboot and a search older than three days are warnings; open security updates
(MSRC severity Critical or Important) too. Events are a warning count: a single error event is
common on a healthy host, so the count shows a trend rather than a fault. A machine
certificate that expires within 14 days is a warning, within 3 days critical; the agent reads
no issue date, so the share of the lifetime left (as the tls sensor rates it) is not known
here. Expired certificates are shown, not alarmed: old ones often stay in the store unused.

Not verified on Windows Server: the field values come from the documented WUA and event log
APIs, not from a run.
"""

MODULE = {
    "id": "windows-host",
    "name": "Windows host",
    "version": 1,
    "description": "Windows: open updates, pending reboot, error events, machine certificates.",
    "detect": {"units": ["EventLog.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "updates",
            "name": "Windows Update",
            "sensor": "host",
            "params": {"view": "win_updates"},
            "interval": 86400,
            "timeout_s": 30,
            "fields": ["updates_open", "updates_security", "reboot_required", "search_age_s"],
            "rules": [
                {"field": "reboot_required", "op": "eq", "value": True, "level": "warning"},
                {"field": "search_age_s", "op": "gt", "value": 259200, "level": "warning"},
                {"field": "updates_security", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
        {
            "key": "events",
            "name": "Error events",
            "sensor": "host",
            "params": {"view": "win_events"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["system", "application", "total"],
            "rules": [{"field": "total", "op": "gt", "value": 0, "level": "warning"}],
        },
        {
            "key": "certs",
            "name": "Machine certificates",
            "sensor": "host",
            "params": {"view": "win_certs"},
            "interval": 86400,
            "fields": ["certs", "expired", "min_days_left"],
            "rules": [
                {"field": "min_days_left", "op": "lt", "value": 3, "level": "critical"},
                {"field": "min_days_left", "op": "lt", "value": 14, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "updates", "field": "updates_open", "label": "Open updates"},
        {"check_key": "updates", "field": "reboot_required", "label": "Reboot required"},
        {"check_key": "events", "field": "total", "label": "Error events"},
        {"check_key": "certs", "field": "min_days_left", "label": "Certificate days left"},
    ],
}
