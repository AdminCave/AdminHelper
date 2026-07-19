# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Built-in template seeding (T5): a fresh DB gets the five standard templates
exactly once; the tombstone in monitor_seed_state guarantees that user
deletions and edits are never overridden by a later startup. The definitions
themselves must pass the same schema boundary as user-created templates."""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.builtin_templates import BUILTIN_TEMPLATES, seed_builtin_templates
from app.models import Base, MonitorSeedState, MonitorTemplate
from app.schemas import TemplateAlertDef, TemplateCheckDef


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def test_fresh_seed_creates_all_builtins(db):
    created = seed_builtin_templates(db)
    assert created == len(BUILTIN_TEMPLATES) == 5

    templates = db.query(MonitorTemplate).all()
    assert {t.builtin_slug for t in templates} == {t["slug"] for t in BUILTIN_TEMPLATES}
    assert {s.slug for s in db.query(MonitorSeedState).all()} == {
        t["slug"] for t in BUILTIN_TEMPLATES
    }
    # Stored JSON round-trips and carries the def_ids the live-sync keys on.
    linux = next(t for t in templates if t.builtin_slug == "linux-base")
    defs = json.loads(linux.check_definitions)
    assert {d["def_id"] for d in defs} == {
        "agent-heartbeat",
        "system-resources",
        "service-health",
        "smart-health",
        "disk-forecast",
    }
    windows = next(t for t in templates if t.builtin_slug == "windows-base")
    windows_defs = json.loads(windows.check_definitions)
    assert "disk-forecast" in {d["def_id"] for d in windows_defs}


def test_second_run_is_idempotent(db):
    assert seed_builtin_templates(db) == 5
    assert seed_builtin_templates(db) == 0
    assert db.query(MonitorTemplate).count() == 5


def test_deleted_builtin_stays_deleted(db):
    seed_builtin_templates(db)
    linux = db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "linux-base").one()
    db.delete(linux)
    db.commit()

    assert seed_builtin_templates(db) == 0
    assert (
        db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "linux-base").first()
        is None
    )


def test_user_edit_is_preserved(db):
    seed_builtin_templates(db)
    linux = db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "linux-base").one()
    linux.name = "My Tuned Linux Template"
    linux.check_definitions = "[]"
    db.commit()

    seed_builtin_templates(db)
    linux = db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "linux-base").one()
    assert linux.name == "My Tuned Linux Template"
    assert linux.check_definitions == "[]"


def test_definitions_pass_the_schema_boundary():
    # Built-ins must satisfy exactly the validation user templates go through —
    # a typo'd config key or invalid interval in a shipped template would
    # otherwise only explode at assign time.
    for tpl in BUILTIN_TEMPLATES:
        for check_def in tpl["check_definitions"]:
            TemplateCheckDef(**check_def)
        for alert_def in tpl["alert_definitions"]:
            TemplateAlertDef(**alert_def)


def test_heartbeat_defs_carry_the_server_id_placeholder():
    # Without {{server_id}} in the config the materialized agent_ping check
    # would evaluate to 'unknown' forever (the checker needs the id to look up
    # the liveness map).
    for tpl in BUILTIN_TEMPLATES:
        for check_def in tpl["check_definitions"]:
            if check_def["check_type"] in ("agent_ping", "disk_forecast"):
                # Both need the id to resolve their data source — without the
                # placeholder the materialized check sits at 'unknown' forever.
                assert check_def["config"]["server_id"] == "{{server_id}}"


def test_slugs_and_def_ids_are_unique():
    slugs = [t["slug"] for t in BUILTIN_TEMPLATES]
    assert len(slugs) == len(set(slugs))
    for tpl in BUILTIN_TEMPLATES:
        def_ids = [d["def_id"] for d in tpl["check_definitions"]]
        assert len(def_ids) == len(set(def_ids)), tpl["slug"]
