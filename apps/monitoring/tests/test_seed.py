# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Built-in template seeding (T5): a fresh DB gets the six standard templates
exactly once; the tombstone in monitor_seed_state guarantees that user
deletions and edits are never overridden by a later startup. The definitions
themselves must pass the same schema boundary as user-created templates.

Versions of the built-ins (R-0420): a built-in nobody changed follows a newer
shipped version on startup, an edited one only offers it."""

import copy
import hashlib
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import builtin_templates, template_sync
from app.builtin_templates import (
    BUILTIN_TEMPLATES,
    BUILTIN_V1_HASHES,
    definitions_hash,
    reconcile_builtin_templates,
    seed_builtin_templates,
)
from app.models import Base, MonitorCheck, MonitorSeedState, MonitorTemplate
from app.routers import templates as templates_router
from app.schemas import TemplateAlertDef, TemplateCheckDef, TemplateUpdate
from app.template_sync import apply_template


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
    assert created == len(BUILTIN_TEMPLATES) == 6

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
        "system-state",
        "smart-health",
        "disk-forecast",
    }
    windows = next(t for t in templates if t.builtin_slug == "windows-base")
    windows_defs = json.loads(windows.check_definitions)
    assert "disk-forecast" in {d["def_id"] for d in windows_defs}
    # The agent reports the system state on Linux only.
    assert "system-state" not in {d["def_id"] for d in windows_defs}


def test_second_run_is_idempotent(db):
    assert seed_builtin_templates(db) == 6
    assert seed_builtin_templates(db) == 0
    assert db.query(MonitorTemplate).count() == 6


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


def test_install_from_before_host_ping_gets_it_on_the_next_start(db, monkeypatch):
    monkeypatch.setattr(
        builtin_templates,
        "BUILTIN_TEMPLATES",
        [t for t in BUILTIN_TEMPLATES if t["slug"] != "host-ping"],
    )
    assert seed_builtin_templates(db) == 5
    docker = db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "docker-host").one()
    db.delete(docker)
    db.commit()
    monkeypatch.setattr(builtin_templates, "BUILTIN_TEMPLATES", BUILTIN_TEMPLATES)

    # Only the new one; the one the user deleted stays deleted.
    assert seed_builtin_templates(db) == 1
    host_ping = db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "host-ping").one()
    assert (host_ping.name, host_ping.builtin_version) == ("Host Ping", 1)
    assert [d["def_id"] for d in json.loads(host_ping.check_definitions)] == ["host-ping"]
    assert {t.builtin_slug for t in db.query(MonitorTemplate)} == {
        t["slug"] for t in BUILTIN_TEMPLATES
    } - {"docker-host"}


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
    validated = set()
    for tpl in BUILTIN_TEMPLATES:
        for check_def in tpl["check_definitions"]:
            TemplateCheckDef(**check_def)
            validated.add(check_def["check_type"])
        for alert_def in tpl["alert_definitions"]:
            TemplateAlertDef(**alert_def)
    # The config of each type goes through its strict model: the new resources
    # keys of linux-base and the empty system_state config included.
    assert {"agent_resources", "system_state"} <= validated


def test_whole_numbers_in_the_shipped_configs_are_int():
    # The desktop editor saves the definitions back as JSON numbers: a shipped 3.0
    # would come back as 3, and the unchanged built-in would count as edited.
    for tpl in BUILTIN_TEMPLATES:
        for check_def in tpl["check_definitions"]:
            for key, value in check_def["config"].items():
                assert not (isinstance(value, float) and value.is_integer()), (tpl["slug"], key)


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


# --- versions of the built-ins (R-0420) -----------------------------------------


@pytest.fixture()
def scheduled(monkeypatch):
    """The checks the template sync schedules, instead of the real scheduler."""
    added: list[str] = []
    monkeypatch.setattr(template_sync, "add_check", lambda cid, interval, ct: added.append(cid))
    monkeypatch.setattr(template_sync, "remove_check", lambda cid: None)
    return added


def _row(db, slug):
    return db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == slug).one()


def _shipped(slug):
    return next(t for t in builtin_templates.BUILTIN_TEMPLATES if t["slug"] == slug)


def _ship_version_2(monkeypatch, slug="linux-base", def_id="system-resources"):
    """Ship a new version of one built-in (the shipped one + 1): its check def_id
    warns every minute."""
    shipped = copy.deepcopy(builtin_templates.BUILTIN_TEMPLATES)
    tpl = next(t for t in shipped if t["slug"] == slug)
    tpl["version"] += 1
    tpl["check_definitions"] = [
        {**d, "severity": "warning", "interval": "1m"} if d["def_id"] == def_id else d
        for d in tpl["check_definitions"]
    ]
    monkeypatch.setattr(builtin_templates, "BUILTIN_TEMPLATES", shipped)
    return tpl


# What the built-ins past version 1 shipped as version 1; the others still ship
# it. Rows seeded before the versions hold these definitions. Like the frozen
# hashes they never change.
_VERSION_1_CHECK_DEFINITIONS = {
    "linux-base": [
        {
            "def_id": "agent-heartbeat",
            "name": "Agent Heartbeat",
            "description": "Alerts when the agent has stopped reporting.",
            "check_type": "agent_ping",
            "config": {"server_id": "{{server_id}}", "stale_minutes": 15},
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 1,
        },
        {
            "def_id": "system-resources",
            "name": "System Resources",
            "description": "CPU, memory, disk and temperature thresholds.",
            "check_type": "agent_resources",
            "config": {
                "cpu_warn": 90,
                "cpu_crit": 95,
                "memory_warn": 90,
                "memory_crit": 98,
                "disk_warn": 80,
                "disk_crit": 90,
                "temp_warn": 80,
                "temp_crit": 95,
            },
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 3,
        },
        {
            "def_id": "service-health",
            "name": "Service Health",
            "description": "Failed and enabled-but-inactive systemd units.",
            "check_type": "service_process",
            "config": {"mode": "auto"},
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 2,
        },
        {
            "def_id": "smart-health",
            "name": "SMART Health",
            "description": "Disk SMART attributes (checker defaults, Backblaze-validated).",
            "check_type": "smart_health",
            "config": {},
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 2,
        },
        {
            "def_id": "disk-forecast",
            "name": "Disk Forecast",
            "description": "Predicts time-until-full from the recent fill rate.",
            "check_type": "disk_forecast",
            "config": {"server_id": "{{server_id}}"},
            "interval": "1h",
            "severity": "warning",
            "consecutive_fails": 1,
        },
    ],
    "windows-base": [
        {
            "def_id": "agent-heartbeat",
            "name": "Agent Heartbeat",
            "description": "Alerts when the agent has stopped reporting.",
            "check_type": "agent_ping",
            "config": {"server_id": "{{server_id}}", "stale_minutes": 15},
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 1,
        },
        {
            "def_id": "system-resources",
            "name": "System Resources",
            "description": "CPU, memory, disk and temperature thresholds.",
            "check_type": "agent_resources",
            "config": {
                "cpu_warn": 90,
                "cpu_crit": 95,
                "memory_warn": 90,
                "memory_crit": 98,
                "disk_warn": 80,
                "disk_crit": 90,
                "temp_warn": 80,
                "temp_crit": 95,
            },
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 3,
        },
        {
            "def_id": "smart-health",
            "name": "SMART Health",
            "description": "Disk SMART attributes (checker defaults, Backblaze-validated).",
            "check_type": "smart_health",
            "config": {},
            "interval": "5m",
            "severity": "critical",
            "consecutive_fails": 2,
        },
        {
            "def_id": "disk-forecast",
            "name": "Disk Forecast",
            "description": "Predicts time-until-full from the recent fill rate.",
            "check_type": "disk_forecast",
            "config": {"server_id": "{{server_id}}"},
            "interval": "1h",
            "severity": "warning",
            "consecutive_fails": 1,
        },
    ],
    "proxmox-host": [
        {
            "def_id": "proxmox-backup",
            "name": "Proxmox Backups",
            "description": "Alerts when a guest has no recent backup.",
            "check_type": "proxmox_backup",
            "config": {"max_backup_age_hours": 26},
            "interval": "5m",
            "severity": "warning",
            "consecutive_fails": 1,
        }
    ],
}


def _version_1(slug):
    """The check definitions version 1 of a built-in shipped, checked against its
    frozen hash."""
    defs = (
        _VERSION_1_CHECK_DEFINITIONS.get(slug)
        or next(t for t in BUILTIN_TEMPLATES if t["slug"] == slug)["check_definitions"]
    )
    assert definitions_hash(defs, []) == BUILTIN_V1_HASHES[slug], slug
    return copy.deepcopy(defs)


def _seed_version_1(db):
    """The built-ins as version 1 rolled them out: its definitions, version 1 and
    the frozen hash."""
    seed_builtin_templates(db)
    for slug, frozen in BUILTIN_V1_HASHES.items():
        row = _row(db, slug)
        row.check_definitions = json.dumps(_version_1(slug))
        row.builtin_version = 1
        row.builtin_hash = frozen
    db.commit()


def _past_version_1():
    """The slugs of the built-ins that ship a version after 1."""
    return {t["slug"] for t in BUILTIN_TEMPLATES if t["version"] > 1}


def _resources_check(db, server_id):
    return (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id, MonitorCheck.template_def_id == "system-resources"
        )
        .one()
    )


def test_definitions_hash_is_sha256_of_the_canonical_json_without_schema_defaults():
    # Pinned: rows in the field carry hashes of this exact form. The router stores
    # every field of a definition (model_dump), the shipped ones leave the defaults
    # out; both have to hash the same. A key at its default drops out ("interval"),
    # any other value stays ("severity").
    canonical = (
        b'[[{"check_type":"smart_health","def_id":"a","name":"A","severity":"warning"}],'
        b'[{"channel":"webhook","def_id":"b","name":"B"}]]'
    )
    check_def = {
        "def_id": "a",
        "name": "A",
        "check_type": "smart_health",
        "interval": "5m",
        "severity": "warning",
    }
    alert_def = {"name": "B", "def_id": "b", "channel": "webhook"}

    expected = hashlib.sha256(canonical).hexdigest()
    assert definitions_hash([check_def], [alert_def]) == expected
    assert (
        definitions_hash(
            [TemplateCheckDef(**check_def).model_dump()],
            [TemplateAlertDef(**alert_def).model_dump()],
        )
        == expected
    )
    assert definitions_hash([{**check_def, "interval": "1m"}], [alert_def]) != expected


def test_shipped_definitions_change_only_with_a_new_version():
    # Every install stores these hashes. A hash may change only because its
    # built-in's definitions changed on purpose, and then together with a higher
    # "version": under the same version the change never reaches an existing
    # install. Any other cause (canonical form, schema) marks the built-in as
    # edited in every install and stops its updates; fix that cause instead.
    pinned = {
        "linux-base": (3, "ead06c5bf0577b4d3c62dc42015ac5b8629ee3605cde311db22b443710eb7c1d"),
        "windows-base": (2, "476b982b2831e947babdbbe0fcde9136e0155a300408a97da333d729d3ec08a0"),
        "proxmox-host": (2, "e894ce48c723a76a29591dbfdc2a19367fb372a2a63458d3a3695fd70f015cbb"),
        "docker-host": (1, "a54b94104244cb22a229e2c67501f546300e40886c552189466c1f3f89cf0d19"),
        "zfs-storage": (1, "2cb8243af6f0e31ac72ae4c526b601a4dd7480408f624d390e83ebc24d0d6932"),
        "host-ping": (1, "394189d1372ffe17265dfa60b8ed25909f858b0259fbc5b30fb9b572eb17c185"),
    }
    assert {
        t["slug"]: (t["version"], definitions_hash(t["check_definitions"], t["alert_definitions"]))
        for t in BUILTIN_TEMPLATES
    } == pinned


def test_frozen_version_1_hashes_never_change():
    # Rows seeded before the versions compare with these for good. Unlike the pins
    # above they do not move with a new version: they stand for what version 1
    # shipped, and as long as a built-in still ships version 1 they are its hash.
    assert BUILTIN_V1_HASHES == {
        "linux-base": "fda790008184ed153f4734a916746a1ed971edb57570b99dbc49d4195a8ecf13",
        "windows-base": "4be77f8ba5a16bc1857dfcf0b2c5ae634967e7d35b97d837a70769ca36b98e70",
        "proxmox-host": "e76eb40daf8b1dffac8dce22b6d174fd25e7eaa44c515810b4aad092260c8b98",
        "docker-host": "a54b94104244cb22a229e2c67501f546300e40886c552189466c1f3f89cf0d19",
        "zfs-storage": "2cb8243af6f0e31ac72ae4c526b601a4dd7480408f624d390e83ebc24d0d6932",
    }
    for tpl in BUILTIN_TEMPLATES:
        if tpl["version"] == 1 and tpl["slug"] in BUILTIN_V1_HASHES:
            assert BUILTIN_V1_HASHES[tpl["slug"]] == definitions_hash(
                tpl["check_definitions"], tpl["alert_definitions"]
            ), tpl["slug"]


def test_seed_records_version_and_hash(db):
    seed_builtin_templates(db)
    db.add(MonitorTemplate(id="own", name="Own", check_definitions="[]", alert_definitions="[]"))
    db.commit()

    for tpl in BUILTIN_TEMPLATES:
        row = _row(db, tpl["slug"])
        assert row.builtin_version == tpl["version"]
        assert row.builtin_hash == definitions_hash(
            tpl["check_definitions"], tpl["alert_definitions"]
        )
        d = templates_router._template_dict(row)
        assert (d["builtinVersion"], d["builtinEdited"], d["builtinUpdateAvailable"]) == (
            tpl["version"],
            False,
            False,
        )
    d = templates_router._template_dict(db.get(MonitorTemplate, "own"))
    assert (d["builtinVersion"], d["builtinEdited"], d["builtinUpdateAvailable"]) == (
        None,
        False,
        False,
    )


def test_unchanged_builtin_follows_a_new_version_and_keeps_check_overrides(
    db, monkeypatch, scheduled
):
    seed_builtin_templates(db)
    linux = _row(db, "linux-base")
    linux.name = "Our Linux"  # name and description are not part of the hash
    db.commit()
    apply_template(db, linux, "srv-1", "web01.example", "Web 01")
    check = _resources_check(db, "srv-1")
    check.interval = "15m"
    check.overridden_fields = json.dumps(["interval"])
    db.commit()
    scheduled.clear()
    v2 = _ship_version_2(monkeypatch)

    assert reconcile_builtin_templates(db) == 1

    linux = _row(db, "linux-base")
    assert json.loads(linux.check_definitions) == v2["check_definitions"]
    assert linux.name == "Our Linux"
    assert linux.builtin_version == v2["version"]
    assert linux.builtin_hash == definitions_hash(v2["check_definitions"], [])
    d = templates_router._template_dict(linux)
    assert (d["builtinVersion"], d["builtinEdited"], d["builtinUpdateAvailable"]) == (
        v2["version"],
        False,
        False,
    )
    # Synced: the severity follows the template, the user's interval stays.
    check = _resources_check(db, "srv-1")
    assert (check.severity, check.interval) == ("warning", "15m")
    assert check.id in scheduled
    # The other built-ins ship no new version and stay as they were.
    assert _row(db, "windows-base").builtin_version == _shipped("windows-base")["version"]


def test_edited_builtin_stays_as_it_is_and_offers_the_update(db, monkeypatch, scheduled):
    seed_builtin_templates(db)
    linux = _row(db, "linux-base")
    edited = json.loads(linux.check_definitions)[:2]
    linux.check_definitions = json.dumps(edited)
    db.commit()
    v2 = _ship_version_2(monkeypatch)

    assert reconcile_builtin_templates(db) == 0

    linux = _row(db, "linux-base")
    assert json.loads(linux.check_definitions) == edited
    assert linux.builtin_version == v2["version"] - 1
    d = templates_router._template_dict(linux)
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (True, True)
    assert scheduled == []


def test_builtin_saved_unchanged_in_the_editor_still_follows_a_new_version(
    db, monkeypatch, scheduled
):
    # The desktop editor sends every definition back on save, even for a rename,
    # and the router stores them with the schema defaults filled in.
    seed_builtin_templates(db)
    linux = _row(db, "linux-base")
    shipped = _shipped("linux-base")
    templates_router.update_template(
        linux.id,
        TemplateUpdate(
            name="Our Linux",
            check_definitions=[TemplateCheckDef(**d) for d in shipped["check_definitions"]],
            alert_definitions=[],
        ),
        db,
    )
    assert json.loads(_row(db, "linux-base").check_definitions) != shipped["check_definitions"]
    assert templates_router._template_dict(_row(db, "linux-base"))["builtinEdited"] is False
    v2 = _ship_version_2(monkeypatch)

    assert reconcile_builtin_templates(db) == 1
    assert (_row(db, "linux-base").builtin_version, _row(db, "linux-base").name) == (
        v2["version"],
        "Our Linux",
    )


def test_a_new_optional_schema_field_leaves_the_builtins_unedited(db, monkeypatch):
    # The hashes stored in every install have to survive a growing schema: a new
    # optional field would otherwise mark every built-in as edited for good.
    seed_builtin_templates(db)

    class GrownCheckDef(TemplateCheckDef):
        hold_minutes: int = 0

    monkeypatch.setattr(builtin_templates, "TemplateCheckDef", GrownCheckDef)

    for tpl in BUILTIN_TEMPLATES:
        assert templates_router._template_dict(_row(db, tpl["slug"]))["builtinEdited"] is False, (
            tpl["slug"]
        )
    # Saved again by the editor, now with the new field at its default.
    linux = _row(db, "linux-base")
    linux.check_definitions = json.dumps(
        [GrownCheckDef(**d).model_dump() for d in _shipped("linux-base")["check_definitions"]]
    )
    db.commit()
    assert templates_router._template_dict(_row(db, "linux-base"))["builtinEdited"] is False


def test_builtin_seeded_before_versions_gets_a_baseline(db, scheduled):
    # Rows seeded before the versions existed: the definitions of version 1, no
    # version, no hash; two of them edited by hand back then, windows-base (a later
    # version ships for it) and docker-host (still at version 1).
    _seed_version_1(db)
    windows = _row(db, "windows-base")
    windows.check_definitions = json.dumps(json.loads(windows.check_definitions)[:1])
    docker = _row(db, "docker-host")
    docker.check_definitions = json.dumps(
        [{**d, "interval": "1m"} for d in json.loads(docker.check_definitions)]
    )
    for row in db.query(MonitorTemplate).all():
        row.builtin_version = None
        row.builtin_hash = None
    db.commit()

    # Version 1 with its frozen hash; the unedited ones a later version ships for
    # follow it, once.
    followed = _past_version_1() - {"windows-base"}
    assert reconcile_builtin_templates(db) == len(followed)
    assert reconcile_builtin_templates(db) == 0

    for tpl in BUILTIN_TEMPLATES:
        row = _row(db, tpl["slug"])
        shipped_hash = definitions_hash(tpl["check_definitions"], tpl["alert_definitions"])
        if tpl["slug"] in followed:
            expected = (tpl["version"], shipped_hash)
        else:
            # host-ping shipped only after the versions: no frozen hash, the shipped one.
            expected = (1, BUILTIN_V1_HASHES.get(tpl["slug"], shipped_hash))
        assert (row.builtin_version, row.builtin_hash) == expected, tpl["slug"]
    # Edited by hand: windows-base offers its newer version, docker-host ships none.
    assert {
        tpl["slug"]: (
            templates_router._template_dict(_row(db, tpl["slug"]))["builtinEdited"],
            templates_router._template_dict(_row(db, tpl["slug"]))["builtinUpdateAvailable"],
        )
        for tpl in BUILTIN_TEMPLATES
    } == {
        "linux-base": (False, False),
        "windows-base": (True, True),
        "proxmox-host": (False, False),
        "docker-host": (True, False),
        "zfs-storage": (False, False),
        "host-ping": (False, False),
    }
    assert scheduled == []


def test_unchanged_install_of_version_1_gives_disk_forecast_consecutive_oks_1(db, scheduled):
    # An install that rolled out version 1 of linux-base and windows-base and
    # assigned them; then the versions with Disk Forecast's consecutive_oks 1 ship.
    _seed_version_1(db)
    apply_template(db, _row(db, "linux-base"), "srv-1", "web01.example", "Web 01")
    apply_template(db, _row(db, "windows-base"), "srv-2", "win01.example", "Win 01")
    assert {check.consecutive_oks for check in db.query(MonitorCheck)} == {2}
    # On one server the user set the Disk Forecast's consecutive_oks by hand.
    customized = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.server_id == "srv-2", MonitorCheck.template_def_id == "disk-forecast")
        .one()
    )
    customized.consecutive_oks = 3
    customized.overridden_fields = json.dumps(["consecutive_oks"])
    db.commit()
    scheduled.clear()

    assert reconcile_builtin_templates(db) == len(_past_version_1())

    assert {slug: _row(db, slug).builtin_version for slug in ("linux-base", "windows-base")} == {
        "linux-base": 3,
        "windows-base": 2,
    }
    got = {
        (check.server_id, check.template_def_id): check.consecutive_oks
        for check in db.query(MonitorCheck)
    }
    # SMART Health runs every 5 minutes and keeps the default, as does every
    # other check; only the hourly Disk Forecast recovers on the first ok.
    assert {key: oks for key, oks in got.items() if oks != 2} == {
        ("srv-1", "disk-forecast"): 1,
        ("srv-2", "disk-forecast"): 3,
    }
    assert (got[("srv-1", "smart-health")], got[("srv-2", "smart-health")]) == (2, 2)


def _forget_versions(db):
    """The rows as seeded before the versions existed: no version, no hash."""
    for row in db.query(MonitorTemplate).all():
        row.builtin_version = None
        row.builtin_hash = None
    db.commit()


@pytest.mark.parametrize(
    ("slug", "def_id"),
    [
        ("linux-base", "system-resources"),
        ("windows-base", "system-resources"),
        ("proxmox-host", "proxmox-backup"),
        ("docker-host", "docker-health"),
        ("zfs-storage", "zfs-health"),
    ],
)
def test_unchanged_builtin_seeded_before_versions_follows_a_new_version(
    db, monkeypatch, scheduled, slug, def_id
):
    # Such a row holds the definitions of version 1. Compared with the frozen hash
    # of version 1, not with what ships now, it follows a newer version like any
    # other unchanged built-in instead of counting as edited.
    _seed_version_1(db)
    apply_template(db, _row(db, slug), "srv-1", "host01.example", "Host 01")
    _forget_versions(db)
    scheduled.clear()
    v2 = _ship_version_2(monkeypatch, slug, def_id)

    assert reconcile_builtin_templates(db) == len(_past_version_1() | {slug})

    row = _row(db, slug)
    assert json.loads(row.check_definitions) == v2["check_definitions"]
    assert (row.builtin_version, row.builtin_hash) == (
        v2["version"],
        definitions_hash(v2["check_definitions"], []),
    )
    d = templates_router._template_dict(row)
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (False, False)
    check = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.server_id == "srv-1", MonitorCheck.template_def_id == def_id)
        .one()
    )
    assert (check.severity, check.interval) == ("warning", "1m")
    assert check.id in scheduled
    # The others, unedited: those still at version 1 keep it with its frozen hash,
    # those past it followed their shipped version.
    for tpl in BUILTIN_TEMPLATES:
        if tpl["slug"] != slug:
            other = _row(db, tpl["slug"])
            shipped_hash = definitions_hash(tpl["check_definitions"], tpl["alert_definitions"])
            if tpl["version"] == 1:
                # host-ping shipped only after the versions: no frozen hash.
                expected = (1, BUILTIN_V1_HASHES.get(tpl["slug"], shipped_hash))
            else:
                expected = (tpl["version"], shipped_hash)
            assert (other.builtin_version, other.builtin_hash) == expected, tpl["slug"]
            assert templates_router._template_dict(other)["builtinEdited"] is False, tpl["slug"]


def _proxmox_check(db):
    return (
        db.query(MonitorCheck)
        .filter(MonitorCheck.server_id == "srv-1", MonitorCheck.template_def_id == "proxmox-backup")
        .one()
    )


@pytest.mark.parametrize("before_versions", [False, True])
def test_unchanged_proxmox_host_of_version_1_takes_two_consecutive_fails(
    db, scheduled, before_versions
):
    # Since an unreadable pvesh is an outage, version 2 waits for a second failed
    # run in a row before it alerts, as Docker and ZFS do. A row of version 1 takes
    # it on startup, one seeded before the versions as well (frozen hash).
    _seed_version_1(db)
    apply_template(db, _row(db, "proxmox-host"), "srv-1", "pve01.example", "PVE 01")
    assert _proxmox_check(db).consecutive_fails == 1
    if before_versions:
        _forget_versions(db)
    scheduled.clear()

    assert reconcile_builtin_templates(db) == len(_past_version_1())

    shipped = _shipped("proxmox-host")
    row = _row(db, "proxmox-host")
    assert json.loads(row.check_definitions) == shipped["check_definitions"]
    assert (row.builtin_version, row.builtin_hash) == (
        shipped["version"],
        definitions_hash(shipped["check_definitions"], []),
    )
    d = templates_router._template_dict(row)
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (False, False)
    check = _proxmox_check(db)
    assert check.consecutive_fails == 2
    assert check.id in scheduled


def _checks_by_def_id(db, server_id):
    return {
        c.template_def_id: c
        for c in db.query(MonitorCheck).filter(MonitorCheck.server_id == server_id)
    }


@pytest.mark.parametrize("before_versions", [False, True])
def test_unchanged_linux_base_of_version_1_takes_the_system_state_and_the_new_thresholds(
    db, scheduled, before_versions
):
    # Version 3 rates swap, inodes and the load per CPU, a disk's percentage only
    # below 20 GB free, and adds the system state. A row of version 1 takes it on
    # startup, one seeded before the versions as well (frozen hash); the fields a
    # user changed on a check stay.
    _seed_version_1(db)
    linux = _row(db, "linux-base")
    apply_template(db, linux, "srv-1", "web01.example", "Web 01")
    apply_template(db, linux, "srv-2", "web02.example", "Web 02")
    assert "system-state" not in _checks_by_def_id(db, "srv-1")
    interval_changed = _resources_check(db, "srv-1")
    interval_changed.interval = "15m"
    interval_changed.overridden_fields = json.dumps(["interval"])
    config_changed = _resources_check(db, "srv-2")
    own_config = {"cpu_warn": 70, "cpu_crit": 85}
    config_changed.config = json.dumps(own_config)
    config_changed.overridden_fields = json.dumps(["config"])
    db.commit()
    if before_versions:
        _forget_versions(db)
    scheduled.clear()

    assert reconcile_builtin_templates(db) == len(_past_version_1())

    shipped = _shipped("linux-base")
    row = _row(db, "linux-base")
    assert json.loads(row.check_definitions) == shipped["check_definitions"]
    assert (row.builtin_version, row.builtin_hash) == (
        shipped["version"],
        definitions_hash(shipped["check_definitions"], []),
    )
    d = templates_router._template_dict(row)
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (False, False)
    shipped_defs = {definition["def_id"]: definition for definition in shipped["check_definitions"]}
    for server_id in ("srv-1", "srv-2"):
        checks = _checks_by_def_id(db, server_id)
        assert sorted(checks) == sorted(shipped_defs)
        state = checks["system-state"]
        assert (
            state.name,
            state.check_type,
            json.loads(state.config),
            state.interval,
            state.severity,
            state.consecutive_fails,
        ) == ("System State", "system_state", {}, "5m", "warning", 1)
        assert state.id in scheduled
    # The values of version 1 plus the new keys of version 3; the interval the
    # user changed stays.
    check = _resources_check(db, "srv-1")
    assert json.loads(check.config) == shipped_defs["system-resources"]["config"]
    assert json.loads(check.config) == {
        "cpu_warn": 90,
        "cpu_crit": 95,
        "memory_warn": 90,
        "memory_crit": 98,
        "disk_warn": 80,
        "disk_crit": 90,
        "disk_min_free_gb": 20,
        "swap_warn": 80,
        "swap_crit": 95,
        "inode_warn": 80,
        "inode_crit": 90,
        "load_warn": 1.5,
        "load_crit": 3,
        "temp_warn": 80,
        "temp_crit": 95,
    }
    assert (check.interval, json.loads(check.overridden_fields)) == ("15m", ["interval"])
    # A config the user changed stays without the new keys; the checker defaults
    # are the same values.
    check = _resources_check(db, "srv-2")
    assert (json.loads(check.config), check.interval) == (own_config, "5m")
    assert json.loads(check.overridden_fields) == ["config"]


def test_edited_builtin_seeded_before_versions_stays_edited_and_offers_the_update(
    db, monkeypatch, scheduled
):
    _seed_version_1(db)
    linux = _row(db, "linux-base")
    edited = json.loads(linux.check_definitions)[:2]
    linux.check_definitions = json.dumps(edited)
    _forget_versions(db)
    _ship_version_2(monkeypatch)

    # The other unedited ones past version 1 follow theirs; this one stays.
    assert reconcile_builtin_templates(db) == len(_past_version_1() - {"linux-base"})

    linux = _row(db, "linux-base")
    assert json.loads(linux.check_definitions) == edited
    assert (linux.builtin_version, linux.builtin_hash) == (1, BUILTIN_V1_HASHES["linux-base"])
    d = templates_router._template_dict(linux)
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (True, True)
    assert scheduled == []


def test_builtin_without_a_frozen_hash_gets_the_shipped_one(db, monkeypatch, scheduled):
    # A built-in that shipped only after the versions has no frozen hash; a row of
    # it without a hash compares with the shipped definitions.
    _seed_version_1(db)
    _forget_versions(db)
    frozen = {k: v for k, v in BUILTIN_V1_HASHES.items() if k != "zfs-storage"}
    monkeypatch.setattr(builtin_templates, "BUILTIN_V1_HASHES", frozen)
    zfs = _shipped("zfs-storage")

    # Only the ones past version 1 follow; zfs-storage ships version 1.
    assert reconcile_builtin_templates(db) == len(_past_version_1())

    row = _row(db, "zfs-storage")
    assert (row.builtin_version, row.builtin_hash) == (
        1,
        definitions_hash(zfs["check_definitions"], zfs["alert_definitions"]),
    )
    assert templates_router._template_dict(row)["builtinEdited"] is False


def test_deleted_builtin_stays_deleted_on_a_new_version(db, monkeypatch, scheduled):
    seed_builtin_templates(db)
    db.delete(_row(db, "linux-base"))
    db.commit()
    _ship_version_2(monkeypatch)

    assert seed_builtin_templates(db) == 0
    assert reconcile_builtin_templates(db) == 0
    assert (
        db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "linux-base").first()
        is None
    )


def test_reconcile_again_changes_nothing(db, monkeypatch, scheduled):
    seed_builtin_templates(db)
    apply_template(db, _row(db, "linux-base"), "srv-1", "web01.example", "Web 01")
    _ship_version_2(monkeypatch)
    assert reconcile_builtin_templates(db) == 1
    before = [
        (t.builtin_slug, t.builtin_version, t.builtin_hash, t.check_definitions)
        for t in db.query(MonitorTemplate).order_by(MonitorTemplate.builtin_slug)
    ]
    checks = db.query(MonitorCheck).count()
    scheduled.clear()

    assert reconcile_builtin_templates(db) == 0

    after = [
        (t.builtin_slug, t.builtin_version, t.builtin_hash, t.check_definitions)
        for t in db.query(MonitorTemplate).order_by(MonitorTemplate.builtin_slug)
    ]
    assert after == before
    assert db.query(MonitorCheck).count() == checks
    assert scheduled == []
