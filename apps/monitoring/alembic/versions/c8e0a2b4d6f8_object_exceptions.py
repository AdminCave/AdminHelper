# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""object exceptions: scope object, effects skip and no_rating

Revision ID: c8e0a2b4d6f8
Revises: b6d8f0a2c4e6
Create Date: 2026-11-27

Exceptions on the objects of a check (docs/features/arch-monitoring-neu-p1c.md, R-1637):
the kind of object and an fnmatch pattern on its name. The columns and an index only:
moving the ignore lists and switched-off checks into exceptions needs the template of a
check resolved, so a start-up step does it (app/exception_migration.py).

The downgrade writes back what stands where the code before it reads it, then drops
what that code does not know: a skip turns the column off, a no_rating puts its name
back into the list of the check's config. It deletes the start-up step's mark, so an
upgrade after it moves the lists again.
"""

import json
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e0a2b4d6f8"
down_revision: Union[str, Sequence[str], None] = "b6d8f0a2c4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen here as the lists were when this revision was written (app/exception_scope.py).
_LIST_KEYS = {
    "mount": "ignore_mounts",
    "disk": "ignore_devices",
    "container": "ignore_containers",
    "guest-backup": "exclude_vmids",
    "service": "ignore",
}
_MASKED = {"[[]": "[", "[*]": "*", "[?]": "?"}
_STANDING = " AND enabled IS TRUE AND ended_at IS NULL AND duration_kind = 'permanent'"
_MIGRATION_MARK = "migration:exceptions-p1c"


def upgrade() -> None:
    op.add_column("monitor_exceptions", sa.Column("object_kind", sa.String(20), nullable=True))
    op.add_column("monitor_exceptions", sa.Column("object_pattern", sa.String(255), nullable=True))
    op.create_index(
        "ix_monitor_exceptions_object",
        "monitor_exceptions",
        ["check_id", "object_kind", "object_pattern"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def _unmask(pattern: str) -> str | None:
    name = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "[":
            char = _MASKED.get(pattern[i : i + 3])
            if char is None:
                return None
            name.append(char)
            i += 3
        elif pattern[i] in "*?":
            return None
        else:
            name.append(pattern[i])
            i += 1
    return "".join(name)


def _entry(kind: str, pattern: str):
    """The list entry the code before reads for the pattern. The service list held
    globs already; a glob on another kind names nothing in an exact list, it goes back
    as written so the admin still sees it."""
    if kind == "service":
        return pattern
    name = _unmask(pattern)
    if name is None:
        return pattern
    if kind == "guest-backup" and re.fullmatch(r"[0-9]+", name):
        return int(name)
    return name


def _load_list(config: dict, key: str) -> list:
    current = config.get(key)
    if isinstance(current, str):  # the service list may be one comma-separated string
        return [s.strip() for s in current.split(",") if s.strip()]
    return list(current) if isinstance(current, list) else []


def _write_back(bind) -> None:
    skips = set(
        bind.execute(
            sa.text(
                "SELECT check_id FROM monitor_exceptions"
                " WHERE scope_kind = 'check' AND effect = 'skip' AND check_id IS NOT NULL"
                + _STANDING
            )
        ).scalars()
    )
    entries: dict[str, list] = {}
    for check_id, kind, pattern in bind.execute(
        sa.text(
            "SELECT check_id, object_kind, object_pattern FROM monitor_exceptions"
            " WHERE scope_kind = 'object' AND effect = 'no_rating'"
            " AND check_id IS NOT NULL AND object_pattern IS NOT NULL"
            + _STANDING
            + " ORDER BY check_id, id"
        )
    ):
        if kind in _LIST_KEYS:
            entries.setdefault(check_id, []).append((_LIST_KEYS[kind], _entry(kind, pattern)))

    for check_id in sorted(skips | entries.keys()):
        row = bind.execute(
            sa.text(
                "SELECT config, overridden_fields, template_id, module_id"
                " FROM monitor_checks WHERE id = :id"
            ),
            {"id": check_id},
        ).first()
        if row is None:
            continue
        try:
            marks = json.loads(row.overridden_fields or "[]")
        except ValueError:
            marks = []
        if not isinstance(marks, list):
            marks = []
        # Only template and module checks carry marks (mark_overrides, mark_module_overrides).
        owned = row.template_id is not None or row.module_id is not None
        if check_id in skips and owned and "enabled" not in marks:
            marks.append("enabled")
        config_text = row.config
        try:
            config = json.loads(row.config or "{}")
        except ValueError:
            config = None
        if isinstance(config, dict):
            changed = False
            for key, entry in entries.get(check_id, ()):
                current = _load_list(config, key)
                if entry not in current:
                    config[key] = [*current, entry]
                    changed = True
            if changed:
                config_text = json.dumps(config)
                # The list was the admin's before the start-up step took it over; without
                # the mark a template sync would write it back to the template's.
                if owned and "config" not in marks:
                    marks.append("config")
        bind.execute(
            sa.text(
                "UPDATE monitor_checks SET config = :config, overridden_fields = :marks,"
                " enabled = CASE WHEN :skip THEN false ELSE enabled END WHERE id = :id"
            ),
            {
                "id": check_id,
                "config": config_text,
                "marks": json.dumps(marks),
                "skip": check_id in skips,
            },
        )


def downgrade() -> None:
    _write_back(op.get_bind())
    op.execute(
        "DELETE FROM monitor_exceptions"
        " WHERE scope_kind = 'object' OR effect IN ('skip', 'no_rating')"
    )
    op.execute(f"DELETE FROM monitor_seed_state WHERE slug = '{_MIGRATION_MARK}'")
    op.drop_index("ix_monitor_exceptions_object", table_name="monitor_exceptions")
    op.drop_column("monitor_exceptions", "object_pattern")
    op.drop_column("monitor_exceptions", "object_kind")
