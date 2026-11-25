# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tag-sync — materializes template→tag bindings into per-server assignments.

The server DB is the only source of tag membership (GET /api/internal/servers
on the hub). ``sync_tag_assignments()`` computes the desired (template, server)
set from all tag bindings and reconciles: missing pairs are created via
``apply_template`` with ``source='tag'``, stale ``source='tag'`` rows are
removed via ``remove_template``. Tag membership never touches manual
assignments — an existing manual assignment for a desired pair simply wins.
A server whose hostname or name in the inventory differs from an assignment
(manual or tag) gets the new values in that assignment, and its checks/alerts
are synced again via ``sync_assignment``, except the fields a user changed.

Best-effort by design: triggered after tag-binding CRUD, by the server's
notify hook (POST /templates/tag-sync after inventory changes) and by a
15-minute scheduler safety net that catches missed notifies."""

from __future__ import annotations

import logging
import threading

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bell_catch_up import AllClear, send_all_clears
from app.core.config import INTERNAL_API_KEY, SERVER_HUB_URL
from app.models import MonitorTemplate, MonitorTemplateAssignment, MonitorTemplateTagAssignment
from app.server_cleanup import cleanup_server, known_server_ids
from app.template_sync import (
    apply_template,
    record_override_baseline,
    remove_template,
    sync_assignment,
)

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

    Returns {"created": n, "removed": m, "refreshed": k} or None when the
    inventory was unavailable (nothing is changed in that case).

    Servers monitoring knows and a non-empty inventory does not are cleaned up like on a
    server deletion: the hub's one cleanup call may have failed (R-1697)."""
    # Taken before the fetch: the hub commits a server before monitoring gets data for it,
    # so an id seen here but missing from the later inventory is really gone.
    known_before = known_server_ids(db)
    if inventory is None:
        inventory = fetch_inventory()
    if inventory is None:
        return None

    servers_by_id: dict[str, dict] = {}
    servers_by_tag: dict[str, list[dict]] = {}
    for srv in inventory:
        if not isinstance(srv, dict) or not srv.get("id"):
            continue
        servers_by_id[srv["id"]] = srv
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
    refreshed = 0
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
        elif _refresh_names(db, assignment, servers_by_id.get(server_id)):
            refreshed += 1

    if servers_by_id:
        _cleanup_orphans(db, known_before - servers_by_id.keys())

    if created or removed or refreshed:
        logger.info(
            "Tag-sync: %d assignment(s) created, %d removed, %d refreshed",
            created,
            removed,
            refreshed,
        )
    return {"created": created, "removed": removed, "refreshed": refreshed}


def _send_clears(clears: list[AllClear]) -> None:
    try:
        send_all_clears(clears)
    except Exception:
        logger.exception("Tag-sync: sending the all-clears of a deleted server failed")


def _send_clears_in_background(clears: list[AllClear]) -> None:
    # The sync must not wait for the hub: a deleted server with many open alarms would hold it
    # up for one hub call each, as the route avoids with a background task (R-1622).
    if clears:
        threading.Thread(target=_send_clears, args=(clears,), daemon=True).start()


def _cleanup_orphans(db: Session, orphans: set[str]) -> None:
    for server_id in sorted(orphans):
        try:
            cleanup_server(db, server_id, send_clears=_send_clears_in_background)
            logger.info("Tag-sync: cleaned up monitoring data of deleted server %s", server_id)
        except Exception:
            db.rollback()
            logger.exception("Tag-sync: cleanup of deleted server %s failed", server_id)


def _refresh_names(db: Session, assignment: MonitorTemplateAssignment, srv: dict | None) -> bool:
    """Bring an assignment's hostname/name in line with the inventory and sync
    its pair again, so {{hostname}}/{{server_name}} follow a rename. False when
    the server is not in the inventory, nothing changed, or the sync failed
    (then rolled back: the old names stay with the checks built from them)."""
    if srv is None:
        return False
    hostname = srv.get("hostname", "")
    server_name = srv.get("name", "")
    if (assignment.server_hostname, assignment.server_name) == (hostname, server_name):
        return False
    template_id, server_id = assignment.template_id, assignment.server_id
    template = db.get(MonitorTemplate, template_id)
    if template is None:
        return False
    try:
        # With the names the checks were built from: compared with the new ones,
        # the old name and config would count as the user's.
        record_override_baseline(db)
        assignment.server_hostname = hostname
        assignment.server_name = server_name
        sync_assignment(db, template, assignment)
        return True
    except Exception:
        db.rollback()
        logger.exception(
            "Tag-sync: refreshing template %s on server %s failed", template_id, server_id
        )
        return False
