# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one-off move of the user's offs and own list entries into exceptions (R-1637,
arch-monitoring-neu-p1c T11): each source case, what the system switched off staying
off, the fallback of a template check onto its template's config, the report, and a
second run changing nothing."""

import json
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app import exception_migration, template_sync
from app.exception_migration import MIGRATION_KEY, apply, migrate_exceptions, plan, report
from app.exception_scope import check_runs
from app.models import (
    MonitorCheck,
    MonitorException,
    MonitorFinding,
    MonitorSeedState,
    MonitorTemplate,
)
from app.template_sync import apply_template


@pytest.fixture()
def db(monkeypatch, db_engine):
    factory = sessionmaker(bind=db_engine)
    # The start takes the override baseline before it migrates.
    with factory() as setup:
        setup.add(MonitorSeedState(slug=template_sync.OVERRIDE_BASELINE_KEY))
        setup.commit()
    monkeypatch.setattr(template_sync, "add_check", lambda *args: None)
    monkeypatch.setattr(template_sync, "remove_check", lambda cid: None)
    session = factory()
    yield session
    session.close()


RES_DEF = {
    "def_id": "res",
    "name": "Resources {{server_name}}",
    "check_type": "agent_resources",
    "config": {"ignore_mounts": ["/boot/efi"], "cpu_warn": 90, "disk_warn": 85},
    "interval": "5m",
    "severity": "warning",
}
PING_DEF = {
    "def_id": "ping",
    "name": "Ping {{server_name}}",
    "check_type": "ping",
    "config": {"host": "{{hostname}}"},
    "interval": "5m",
    "severity": "critical",
}


def _template_check(db, check_def, *, config=None, enabled=True, marks=()):
    """A template check as the code before P1c left it: its config, column and marks."""
    tpl = MonitorTemplate(
        id=str(uuid.uuid4()),
        name="Linux Base",
        check_definitions=json.dumps([check_def]),
        alert_definitions="[]",
    )
    db.add(tpl)
    db.commit()
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    check = db.query(MonitorCheck).filter_by(template_id=tpl.id).one()
    if config is not None:
        check.config = json.dumps(config)
    check.enabled = enabled
    check.overridden_fields = json.dumps(list(marks))
    db.commit()
    return check


def _check(db, check_type="ping", *, config=None, enabled=True, marks=(), **columns):
    check = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id="srv-1",
        name=f"{check_type} check",
        check_type=check_type,
        config=json.dumps(config or {}),
        interval="5m",
        severity="critical",
        enabled=enabled,
        overridden_fields=json.dumps(list(marks)),
        **columns,
    )
    db.add(check)
    db.commit()
    return check


def _module_check(db, *, enabled=False, marks=("enabled",)):
    return _check(
        db,
        enabled=enabled,
        marks=marks,
        module_id="nginx",
        module_instance="default",
        module_check_key="http",
    )


def _instance_gone(db):
    db.add(
        MonitorFinding(
            id=str(uuid.uuid4()),
            server_id="srv-1",
            module_id="nginx",
            instance_key="default",
            kind="gone",
            status="adopted",
            catalog_version="sha256:" + "0" * 64,
        )
    )
    db.commit()


def _exceptions(db, check_id):
    return sorted(
        (x.effect, x.object_kind, x.object_pattern, x.origin, x.created_by, x.created_by_id)
        for x in db.query(MonitorException).filter_by(check_id=check_id)
    )


def _state(db, check):
    db.refresh(check)
    return json.loads(check.config), check.enabled, json.loads(check.overridden_fields)


SKIP = ("skip", None, None, "migration", None, None)


# --- the user's off ------------------------------------------------------------------


def test_a_manual_check_switched_off_becomes_a_skip_with_its_column_on(db):
    check = _check(db, enabled=False)

    assert migrate_exceptions(db) == 1

    assert _exceptions(db, check.id) == [SKIP]
    assert _state(db, check) == ({}, True, [])
    assert not check_runs(db, check)


def test_a_template_check_the_user_switched_off_loses_the_mark(db):
    check = _template_check(db, PING_DEF, enabled=False, marks=["enabled"])

    migrate_exceptions(db)

    assert _exceptions(db, check.id) == [SKIP]
    assert _state(db, check)[1:] == (True, [])
    assert not check_runs(db, check)


def test_a_module_check_the_user_switched_off_loses_the_mark(db):
    check = _module_check(db)

    migrate_exceptions(db)

    assert _exceptions(db, check.id) == [SKIP]
    assert _state(db, check) == ({}, True, [])


def test_the_users_off_on_a_gone_instance_keeps_the_column_off(db):
    # Adopting the gone instance switched it off as well: the system's off stays, the
    # user's becomes the skip that holds when the instance comes back.
    check = _module_check(db)
    _instance_gone(db)

    migrate_exceptions(db)

    assert _exceptions(db, check.id) == [SKIP]
    assert _state(db, check) == ({}, False, [])


def test_the_users_off_on_a_template_that_switches_it_off_keeps_the_column_off(db):
    check = _template_check(db, {**PING_DEF, "enabled": False}, enabled=False, marks=["enabled"])

    migrate_exceptions(db)

    assert _exceptions(db, check.id) == [SKIP]
    assert _state(db, check)[1:] == (False, [])


@pytest.mark.parametrize("source", ["template", "module", "gone instance"])
def test_an_off_of_the_system_stays_and_gets_no_skip(db, source):
    if source == "template":
        check = _template_check(db, {**PING_DEF, "enabled": False}, enabled=False)
    else:
        check = _module_check(db, marks=())
        if source == "gone instance":
            _instance_gone(db)

    assert plan(db) == []
    migrate_exceptions(db)

    assert _exceptions(db, check.id) == []
    assert _state(db, check)[1] is False


# --- the lists -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("check_type", "key", "entries", "kind", "patterns", "unstable"),
    [
        ("agent_resources", "ignore_mounts", ["/srv/data"], "mount", ["/srv/data"], False),
        ("smart_health", "ignore_devices", ["/dev/sdb"], "disk", ["/dev/sdb"], True),
        ("docker_health", "ignore_containers", ["web[1]"], "container", ["web[[]1]"], True),
        ("proxmox_backup", "exclude_vmids", [101, "102"], "guest-backup", ["101"], False),
        ("service_process", "ignore", "cron*, a.service", "service", ["cron*", "a.service"], False),
    ],
)
def test_each_own_list_entry_becomes_a_no_rating_exception_without_an_actor(
    db, check_type, key, entries, kind, patterns, unstable
):
    check = _check(db, check_type, config={key: entries, "other": 1})

    changes = plan(db)
    rows = report(changes)
    apply(db, changes)
    db.commit()

    assert _exceptions(db, check.id) == sorted(
        ("no_rating", kind, p, "migration", None, None) for p in patterns
    )
    assert [x["unstable"] for x in rows[0]["exceptions"]] == [unstable] * len(patterns)
    # A VMID as a string takes no exception, as through the API: it stays in the list.
    kept = ["102"] if kind == "guest-backup" else []
    assert _state(db, check)[0] == {key: kept, "other": 1}


def test_a_template_entry_stays_in_the_config_and_takes_no_exception(db):
    check = _template_check(
        db,
        RES_DEF,
        config={**RES_DEF["config"], "ignore_mounts": ["/boot/efi", "/srv/data"]},
        marks=["config"],
    )

    migrate_exceptions(db)

    assert [x[2] for x in _exceptions(db, check.id)] == ["/srv/data"]
    assert _state(db, check) == (RES_DEF["config"], True, [])


def test_an_unreadable_config_keeps_its_list_and_the_off_still_moves(db):
    check = _check(db, "agent_resources", enabled=False)
    check.config = "{not json"
    db.commit()

    migrate_exceptions(db)

    assert _exceptions(db, check.id) == [SKIP]
    db.refresh(check)
    assert (check.config, check.enabled) == ("{not json", True)


def test_a_template_check_whose_definitions_are_unreadable_stays_as_it_is(db):
    check = _template_check(db, PING_DEF, enabled=False, marks=["enabled"])
    db.get(MonitorTemplate, check.template_id).check_definitions = "{not json"
    manual = _check(db, enabled=False)
    db.commit()

    migrate_exceptions(db)

    assert _exceptions(db, check.id) == []
    assert _state(db, check)[1:] == (False, ["enabled"])
    # The other checks still move.
    assert _exceptions(db, manual.id) == [SKIP]


# --- the fallback onto the template ---------------------------------------------------


def test_a_config_that_differed_only_by_its_list_falls_back_on_the_template(db):
    # From an older template version: disk_warn came with the template since. The mark
    # falls, the config is the template's, the report names old and new values.
    check = _template_check(
        db,
        RES_DEF,
        config={"ignore_mounts": ["/boot/efi", "/srv/data"], "cpu_warn": 90},
        marks=["config", "severity"],
    )

    rows = report(plan(db))
    migrate_exceptions(db)

    assert _state(db, check) == (RES_DEF["config"], True, ["severity"])
    assert rows == [
        {
            "check_id": check.id,
            "name": check.name,
            "server_id": "srv-1",
            "skip": False,
            "exceptions": [{"kind": "mount", "pattern": "/srv/data", "unstable": False}],
            "fallback": True,
            "config": {
                "disk_warn": [None, 85],
                "ignore_mounts": [["/boot/efi", "/srv/data"], ["/boot/efi"]],
            },
            "marks": [["config", "severity"], ["severity"]],
        }
    ]
    assert "back on the template's config" in exception_migration._text(
        {"migrated": False, "checks": rows}
    )


def test_an_own_entry_moves_while_a_template_entry_left_out_keeps_the_mark(db):
    # As through the API: the own entry becomes an exception, leaving out /boot/efi stays
    # the config's override, so the check is no candidate to fall back.
    check = _template_check(
        db, RES_DEF, config={**RES_DEF["config"], "ignore_mounts": ["/srv/data"]}, marks=["config"]
    )

    rows = report(plan(db))
    migrate_exceptions(db)

    assert _state(db, check) == ({**RES_DEF["config"], "ignore_mounts": []}, True, ["config"])
    assert [x[2] for x in _exceptions(db, check.id)] == ["/srv/data"]
    assert rows[0]["fallback"] is False and "own_values" not in rows[0]


def test_an_own_entry_next_to_an_own_threshold_moves_and_the_mark_stays(db):
    check = _template_check(
        db,
        RES_DEF,
        config={**RES_DEF["config"], "ignore_mounts": ["/boot/efi", "/srv/data"], "cpu_warn": 95},
        marks=["config"],
    )

    rows = report(plan(db))
    migrate_exceptions(db)

    assert _state(db, check) == ({**RES_DEF["config"], "cpu_warn": 95}, True, ["config"])
    assert [x[2] for x in _exceptions(db, check.id)] == ["/srv/data"]
    assert rows[0]["own_values"] == ["cpu_warn"]


def test_a_template_entry_left_out_stays_an_override(db):
    _template_check(
        db, RES_DEF, config={**RES_DEF["config"], "ignore_mounts": []}, marks=["config"]
    )

    assert plan(db) == []


def test_a_check_type_of_the_users_keeps_its_config(db):
    _template_check(
        db,
        RES_DEF,
        config={**RES_DEF["config"], "ignore_mounts": ["/boot/efi", "/srv/data"]},
        marks=["check_type", "config"],
    )

    changes = plan(db)

    assert [(c.fallback, c.marks) for c in changes] == [(False, None)]


# --- once ------------------------------------------------------------------------------


def test_a_second_plan_and_apply_change_nothing(db):
    check = _template_check(
        db,
        RES_DEF,
        config={**RES_DEF["config"], "ignore_mounts": ["/boot/efi", "/srv/data"]},
        enabled=False,
        marks=["config", "enabled"],
    )
    changes = plan(db)
    apply(db, changes)
    db.commit()
    before = (_exceptions(db, check.id), _state(db, check))

    assert plan(db) == []
    apply(db, changes)  # the same changes again add no exception twice
    db.commit()

    assert (_exceptions(db, check.id), _state(db, check)) == before


def test_the_start_step_runs_once(db):
    _check(db, enabled=False)
    assert migrate_exceptions(db) == 1
    assert db.get(MonitorSeedState, MIGRATION_KEY) is not None

    later = _check(db, enabled=False)

    assert migrate_exceptions(db) == 0
    assert _exceptions(db, later.id) == []
    assert _state(db, later)[1] is False
