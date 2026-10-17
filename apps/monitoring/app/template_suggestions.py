# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template suggestions from the agent's host facts (R-0421).

store_host_facts() keeps what a server's agent last reported in the ``host`` block
of its report, checked and bounded, as the basis of the suggestions.
suggest_templates() derives the standard templates those facts suggest, and
dismiss_suggestion() remembers one an admin ignored on a server.
"""

from __future__ import annotations

import json
import logging
import uuid

from pydantic import field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.bounds import RequestModel
from app.core.time import utcnow_naive
from app.models import (
    MonitorHostFacts,
    MonitorTemplate,
    MonitorTemplateAssignment,
    MonitorTemplateSuggestionDismissal,
)

logger = logging.getLogger(__name__)

_OSES = frozenset({"linux", "windows", "darwin"})
# Also the stored order, whatever order the agent sent them in.
_SUBSYSTEMS = ("docker", "zfs", "proxmox")
_MAX_TEXT = 64

# The standard template (built-in slug) a reported OS or subsystem suggests;
# darwin has none.
_OS_TEMPLATES = {"linux": "linux-base", "windows": "windows-base"}
_SUBSYSTEM_TEMPLATES = {"docker": "docker-host", "zfs": "zfs-storage", "proxmox": "proxmox-host"}
SUGGESTED_SLUGS = frozenset({*_OS_TEMPLATES.values(), *_SUBSYSTEM_TEMPLATES.values()})


class SuggestionDismiss(RequestModel):
    slug: str

    @field_validator("slug")
    @classmethod
    def _slug_suggested(cls, v: str) -> str:
        if v not in SUGGESTED_SLUGS:
            raise ValueError(f"slug must be one of {', '.join(sorted(SUGGESTED_SLUGS))}")
        return v


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


def suggest_templates(db: Session, server_id: str) -> list[dict]:
    """The standard templates the server's host facts suggest, the OS first: only
    those whose template exists, that are not assigned to the server (from any
    source, manual or tag) and that were not dismissed there. No facts, none."""
    facts = db.get(MonitorHostFacts, server_id)
    if facts is None:
        return []
    reasons: dict[str, str] = {}
    if facts.os in _OS_TEMPLATES:
        reasons[_OS_TEMPLATES[facts.os]] = f"os:{facts.os}"
    subsystems = json.loads(facts.subsystems)
    for name in _SUBSYSTEMS:
        if name in subsystems:
            reasons[_SUBSYSTEM_TEMPLATES[name]] = f"subsystem:{name}"
    if not reasons:
        return []

    templates = {
        t.builtin_slug: t
        for t in db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug.in_(list(reasons)))
    }
    assigned = {
        template_id
        for (template_id,) in db.query(MonitorTemplateAssignment.template_id).filter(
            MonitorTemplateAssignment.server_id == server_id
        )
    }
    dismissed = {
        slug
        for (slug,) in db.query(MonitorTemplateSuggestionDismissal.builtin_slug).filter(
            MonitorTemplateSuggestionDismissal.server_id == server_id
        )
    }
    suggestions = []
    for slug, reason in reasons.items():
        template = templates.get(slug)
        if template is None or template.id in assigned or slug in dismissed:
            continue
        suggestions.append(
            {
                "slug": slug,
                "templateId": template.id,
                "templateName": template.name,
                "reason": reason,
            }
        )
    return suggestions


def dismiss_suggestion(db: Session, server_id: str, slug: str) -> bool:
    """Remember that an admin ignored the suggestion of this standard template on
    this server; idempotent. False, and nothing stored, for a server without host
    facts: nothing was suggested there, and its row could belong to an id that
    cleanup_server is never called for."""
    if db.get(MonitorHostFacts, server_id) is None:
        return False
    db.add(
        MonitorTemplateSuggestionDismissal(
            id=str(uuid.uuid4()), server_id=server_id, builtin_slug=slug
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Dismissed before, or by a concurrent call: the unique constraint keeps the
        # one row there is.
        db.rollback()
    return True
