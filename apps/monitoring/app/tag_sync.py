# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tag-sync — materializes template→tag bindings into per-server assignments.

The server DB is the only source of tag membership (GET /api/internal/servers
on the hub). ``sync_tag_assignments()`` computes the desired (template, server)
set from all tag bindings and reconciles: missing pairs are created via
``apply_template`` with ``source='tag'``, stale ``source='tag'`` rows are
removed via ``remove_template``. Manual assignments are never touched — an
existing manual assignment for a desired pair simply wins.

Best-effort by design: triggered after tag-binding CRUD, by the server's
notify hook (POST /templates/tag-sync after inventory changes) and by a
15-minute scheduler safety net that catches missed notifies."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import INTERNAL_API_KEY, SERVER_HUB_URL
from app.models import MonitorTemplate, MonitorTemplateAssignment, MonitorTemplateTagAssignment
from app.template_sync import apply_template, remove_template

logger = logging.getLogger("monitor.tag_sync")


def fetch_inventory() -> list[dict] | None:
    """Fetch the server inventory from the hub; None on any failure.

    None (as opposed to []) means "unknown" — the caller must NOT reconcile
    against it, or a hub outage would tear down every materialized assignment."""
    if not SERVER_HUB_URL or not INTERNAL_API_KEY:
        return None
    try:
        resp = httpx.get(
            f"{SERVER_HUB_URL}/api/internal/servers",
            headers={"X-Internal-Key": INTERNAL_API_KEY},
            timeout=10,
            follow_redirects=False,
        )
        if resp.status_code != 200:
            logger.warning("Tag-sync inventory fetch rejected: HTTP %s", resp.status_code)
            return None
        data = resp.json()
        return data if isinstance(data, list) else None
    except Exception as exc:
        logger.warning("Tag-sync inventory fetch failed: %s", exc)
        return None


def sync_tag_assignments(db: Session, inventory: list[dict] | None = None) -> dict | None:
    """Reconcile materialized tag assignments against the server inventory.

    Returns {"created": n, "removed": m} or None when the inventory was
    unavailable (nothing is changed in that case)."""
    if inventory is None:
        inventory = fetch_inventory()
    if inventory is None:
        return None

    servers_by_tag: dict[str, list[dict]] = {}
    for srv in inventory:
        if not isinstance(srv, dict) or not srv.get("id"):
            continue
        for tag in srv.get("tags") or []:
            servers_by_tag.setdefault(tag, []).append(srv)

    desired: dict[tuple[str, str], dict] = {}
    for binding in db.query(MonitorTemplateTagAssignment).all():
        for srv in servers_by_tag.get(binding.tag, []):
            desired[(binding.template_id, srv["id"])] = srv

    existing = {(a.template_id, a.server_id): a for a in db.query(MonitorTemplateAssignment).all()}

    created = 0
    for (template_id, server_id), srv in desired.items():
        if (template_id, server_id) in existing:
            continue  # manual assignment wins; materialized one already there
        template = db.get(MonitorTemplate, template_id)
        if template is None:
            continue
        try:
            apply_template(
                db,
                template,
                server_id,
                srv.get("hostname", ""),
                srv.get("name", ""),
                source="tag",
            )
            created += 1
        except IntegrityError:
            # Lost a race against a concurrent assign of the same pair — the
            # unique constraint already guarantees the desired end state.
            db.rollback()
        except Exception:
            db.rollback()
            logger.exception(
                "Tag-sync: applying template %s to server %s failed", template_id, server_id
            )

    removed = 0
    for (template_id, server_id), assignment in existing.items():
        if assignment.source == "tag" and (template_id, server_id) not in desired:
            try:
                remove_template(db, template_id, server_id)
                removed += 1
            except Exception:
                db.rollback()
                logger.exception(
                    "Tag-sync: removing template %s from server %s failed",
                    template_id,
                    server_id,
                )

    if created or removed:
        logger.info("Tag-sync: %d assignment(s) created, %d removed", created, removed)
    return {"created": created, "removed": removed}
