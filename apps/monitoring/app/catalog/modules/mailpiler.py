# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MailPiler from its unit (R-1239).

The module is found by piler.service, the archiving daemon of MailPiler's systemd units
(piler.service, piler-smtp.service, pilersearch.service). Every 15 minutes the agent's app
sensor asks the archive's database on the socket of this host, with the user, database and
password piler.conf names, for the arrival of the newest mail; the password goes to the
database client in its environment and does not leave the host. A newest mail older than two
days warns: the archive takes no more mail. An archive without any mail says archived false
and has no age, so the check stays unknown until the first mail.

Not covered: piler-smtp and the search (their units), a database on another host, and
MailPiler in a container.
"""

MODULE = {
    "id": "mailpiler",
    "name": "MailPiler",
    "version": 1,
    "description": (
        "MailPiler from its unit: the archiving daemon and the age of the newest mail in "
        "the archive."
    ),
    "detect": {"units": ["piler.service"]},
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
            "key": "archive",
            "name": "Archive",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "piler_status"},
            "interval": 900,
            "fields": ["archived", "last_age_s"],
            "rules": [
                {"field": "last_age_s", "op": "gt", "value": 172800, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "archive", "field": "last_age_s", "label": "Newest mail s"},
    ],
}
