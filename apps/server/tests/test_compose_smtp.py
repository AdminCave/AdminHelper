# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compose hands the SMTP relay to every service that sends mail (R-0634).

The monitoring docs promise that the e-mail channel of the alert rules takes
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM from the
environment, overridable per rule. Compose set them on server and scheduler
only, so monitoring fell back to its own defaults, an empty SMTP_HOST among them,
and every e-mail rule without a smtp_host of its own failed with "SMTP not
configured". test_env_parity cannot
see this: a key that compose leaves out of a service which reads it with a
default is no drift there.

The relay is one setting for the whole install, so monitoring takes the five
entries word for word as the server has them, defaults included.
"""

import re
from pathlib import Path

from .test_env_parity import _compose_environment

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
_SMTP_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
_MAIL_SERVICES = ("server", "scheduler", "monitoring")
# One of the five entries, quoted or not; group 1 the entry, group 2 its key.
_SMTP_ENTRY = re.compile(r'^\s+-\s*"?((SMTP_(?:HOST|PORT|USER|PASSWORD|FROM))=[^"]*?)"?\s*$')


def _smtp_entries(service: str) -> dict[str, str]:
    """The `- SMTP_…=…` entries in the `environment:` block of one service, key -> entry.

    Walks the blocks like test_env_parity._compose_environment, which yields keys only.
    """
    entries: dict[str, str] = {}
    current, in_env = None, False
    for line in _COMPOSE.read_text(encoding="utf-8").splitlines():
        header = re.match(r"^  ([A-Za-z][\w-]*):\s*$", line)
        if header:
            current, in_env = header.group(1), False
            continue
        if re.match(r"^    environment:\s*$", line):
            in_env = True
            continue
        if re.match(r"^    \S", line):
            in_env = False
            continue
        if in_env and current == service:
            entry = _SMTP_ENTRY.match(line)
            if entry:
                entries[entry.group(2)] = entry.group(1)
    return entries


def test_every_mail_sending_service_gets_the_smtp_variables():
    compose = _compose_environment()
    missing = {
        service: sorted(set(_SMTP_KEYS) - compose[service])
        for service in _MAIL_SERVICES
        if set(_SMTP_KEYS) - compose[service]
    }
    assert missing == {}, f"compose does not hand these services the SMTP relay: {missing}"


def test_monitoring_gets_the_same_smtp_entries_as_the_server():
    server, monitoring = _smtp_entries("server"), _smtp_entries("monitoring")
    # Non-empty guard: a parse that finds nothing on both sides would compare equal.
    for service, entries in (("server", server), ("monitoring", monitoring)):
        assert sorted(entries) == sorted(_SMTP_KEYS), f"{service}: parsed {sorted(entries)}"
    assert monitoring == server
