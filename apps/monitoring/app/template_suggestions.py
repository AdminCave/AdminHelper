# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template suggestions from the agent's host facts (R-0421).

store_host_facts() keeps what a server's agent last reported in the ``host`` block
of its report, checked and bounded, as the basis of the suggestions.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.core.time import utcnow_naive
from app.models import MonitorHostFacts

logger = logging.getLogger(__name__)

_OSES = frozenset({"linux", "windows", "darwin"})
# Also the stored order, whatever order the agent sent them in.
_SUBSYSTEMS = ("docker", "zfs", "proxmox")
_MAX_TEXT = 64


def _text(value: object) -> str | None:
    """A reported string cut to _MAX_TEXT, or None for "" and for anything else."""
    if not isinstance(value, str):
        return None
    return value[:_MAX_TEXT] or None


def store_host_facts(db: Session, server_id: str, host: dict) -> None:
    """Upsert the host facts of one report. Unknown values and values of the wrong
    type cost only their own field. Own commit, a failure is only logged: like the
    liveness, it must never cost the report."""
    os_name = host.get("os")
    virt = host.get("virtualization")
    if not isinstance(virt, dict):
        virt = {}
    subsystems = host.get("subsystems")
    if not isinstance(subsystems, list):
        subsystems = []
    facts = MonitorHostFacts(
        server_id=server_id,
        os=os_name if isinstance(os_name, str) and os_name in _OSES else None,
        platform=_text(host.get("platform")),
        platform_version=_text(host.get("platform_version")),
        virt_system=_text(virt.get("system")),
        virt_role=_text(virt.get("role")),
        # `in` on the list compares instead of hashing, so an entry that is a list
        # or an object cannot raise here.
        subsystems=json.dumps([name for name in _SUBSYSTEMS if name in subsystems]),
        # Explicit, not the column's onupdate: that fires only with an UPDATE, and
        # unchanged facts would not emit one. updated_at is "last reported".
        updated_at=utcnow_naive(),
    )
    try:
        db.merge(facts)
        db.commit()
    except Exception as exc:
        db.rollback()
        # No traceback: an agent can trigger this on every report.
        logger.error("Storing the host facts failed (%s): %s", server_id, type(exc).__name__)
