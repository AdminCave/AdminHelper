# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Built-in template seeding (T5): a fresh DB gets the five standard templates
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
    """Ship version 2 of one built-in: its check def_id warns every minute."""
    shipped = copy.deepcopy(builtin_templates.BUILTIN_TEMPLATES)
    tpl = next(t for t in shipped if t["slug"] == slug)
    tpl["version"] = 2
    tpl["check_definitions"] = [
        {**d, "severity": "warning", "interval": "1m"} if d["def_id"] == def_id else d
        for d in tpl["check_definitions"]
    ]
    monkeypatch.setattr(builtin_templates, "BUILTIN_TEMPLATES", shipped)
    return tpl


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
        "linux-base": (1, "fda790008184ed153f4734a916746a1ed971edb57570b99dbc49d4195a8ecf13"),
        "windows-base": (1, "4be77f8ba5a16bc1857dfcf0b2c5ae634967e7d35b97d837a70769ca36b98e70"),
        "proxmox-host": (1, "e76eb40daf8b1dffac8dce22b6d174fd25e7eaa44c515810b4aad092260c8b98"),
        "docker-host": (1, "a54b94104244cb22a229e2c67501f546300e40886c552189466c1f3f89cf0d19"),
        "zfs-storage": (1, "2cb8243af6f0e31ac72ae4c526b601a4dd7480408f624d390e83ebc24d0d6932"),
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
        assert row.builtin_version == 1
        assert row.builtin_hash == definitions_hash(
            tpl["check_definitions"], tpl["alert_definitions"]
        )
        d = row.to_dict()
        assert (d["builtinVersion"], d["builtinEdited"], d["builtinUpdateAvailable"]) == (
            1,
            False,
            False,
        )
    d = db.get(MonitorTemplate, "own").to_dict()
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
    assert linux.builtin_version == 2
    assert linux.builtin_hash == definitions_hash(v2["check_definitions"], [])
    d = linux.to_dict()
    assert (d["builtinVersion"], d["builtinEdited"], d["builtinUpdateAvailable"]) == (
        2,
        False,
        False,
    )
    # Synced: the severity follows the template, the user's interval stays.
    check = _resources_check(db, "srv-1")
    assert (check.severity, check.interval) == ("warning", "15m")
    assert check.id in scheduled
    # The other built-ins ship no new version and stay as they were.
    assert _row(db, "windows-base").builtin_version == 1


def test_edited_builtin_stays_as_it_is_and_offers_the_update(db, monkeypatch, scheduled):
    seed_builtin_templates(db)
    linux = _row(db, "linux-base")
    edited = json.loads(linux.check_definitions)[:2]
    linux.check_definitions = json.dumps(edited)
    db.commit()
    _ship_version_2(monkeypatch)

    assert reconcile_builtin_templates(db) == 0

    linux = _row(db, "linux-base")
    assert json.loads(linux.check_definitions) == edited
    assert linux.builtin_version == 1
    d = linux.to_dict()
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
    assert _row(db, "linux-base").to_dict()["builtinEdited"] is False
    _ship_version_2(monkeypatch)

    assert reconcile_builtin_templates(db) == 1
    assert (_row(db, "linux-base").builtin_version, _row(db, "linux-base").name) == (
        2,
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
        assert _row(db, tpl["slug"]).to_dict()["builtinEdited"] is False, tpl["slug"]
    # Saved again by the editor, now with the new field at its default.
    linux = _row(db, "linux-base")
    linux.check_definitions = json.dumps(
        [GrownCheckDef(**d).model_dump() for d in _shipped("linux-base")["check_definitions"]]
    )
    db.commit()
    assert _row(db, "linux-base").to_dict()["builtinEdited"] is False


def test_builtin_seeded_before_versions_gets_a_baseline(db, scheduled):
    seed_builtin_templates(db)
    # Rows seeded before the versions existed: no version, no hash; one of them
    # edited by hand back then.
    windows = _row(db, "windows-base")
    windows.check_definitions = json.dumps(json.loads(windows.check_definitions)[:1])
    for row in db.query(MonitorTemplate).all():
        row.builtin_version = None
        row.builtin_hash = None
    db.commit()

    assert reconcile_builtin_templates(db) == 0
    assert reconcile_builtin_templates(db) == 0

    for tpl in BUILTIN_TEMPLATES:
        row = _row(db, tpl["slug"])
        assert row.builtin_version == 1
        assert row.builtin_hash == definitions_hash(
            tpl["check_definitions"], tpl["alert_definitions"]
        )
    assert _row(db, "linux-base").to_dict()["builtinEdited"] is False
    d = _row(db, "windows-base").to_dict()
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (True, False)
    assert scheduled == []


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
    # of version 1, not with what ships now, it follows version 2 like any other
    # unchanged built-in instead of counting as edited.
    seed_builtin_templates(db)
    apply_template(db, _row(db, slug), "srv-1", "host01.example", "Host 01")
    _forget_versions(db)
    scheduled.clear()
    v2 = _ship_version_2(monkeypatch, slug, def_id)

    assert reconcile_builtin_templates(db) == 1

    row = _row(db, slug)
    assert json.loads(row.check_definitions) == v2["check_definitions"]
    assert (row.builtin_version, row.builtin_hash) == (
        2,
        definitions_hash(v2["check_definitions"], []),
    )
    d = row.to_dict()
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (False, False)
    check = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.server_id == "srv-1", MonitorCheck.template_def_id == def_id)
        .one()
    )
    assert (check.severity, check.interval) == ("warning", "1m")
    assert check.id in scheduled
    # The others ship no new version: version 1 with its frozen hash, unedited.
    for tpl in BUILTIN_TEMPLATES:
        if tpl["slug"] != slug:
            other = _row(db, tpl["slug"])
            assert (other.builtin_version, other.builtin_hash) == (
                1,
                BUILTIN_V1_HASHES[tpl["slug"]],
            )
            assert other.to_dict()["builtinEdited"] is False, tpl["slug"]


def test_edited_builtin_seeded_before_versions_stays_edited_and_offers_the_update(
    db, monkeypatch, scheduled
):
    seed_builtin_templates(db)
    linux = _row(db, "linux-base")
    edited = json.loads(linux.check_definitions)[:2]
    linux.check_definitions = json.dumps(edited)
    _forget_versions(db)
    _ship_version_2(monkeypatch)

    assert reconcile_builtin_templates(db) == 0

    linux = _row(db, "linux-base")
    assert json.loads(linux.check_definitions) == edited
    assert (linux.builtin_version, linux.builtin_hash) == (1, BUILTIN_V1_HASHES["linux-base"])
    d = linux.to_dict()
    assert (d["builtinEdited"], d["builtinUpdateAvailable"]) == (True, True)
    assert scheduled == []


def test_builtin_without_a_frozen_hash_gets_the_shipped_one(db, monkeypatch, scheduled):
    # A built-in that shipped only after the versions has no frozen hash; a row of
    # it without a hash compares with the shipped definitions.
    seed_builtin_templates(db)
    _forget_versions(db)
    frozen = {k: v for k, v in BUILTIN_V1_HASHES.items() if k != "zfs-storage"}
    monkeypatch.setattr(builtin_templates, "BUILTIN_V1_HASHES", frozen)
    zfs = _shipped("zfs-storage")

    assert reconcile_builtin_templates(db) == 0

    row = _row(db, "zfs-storage")
    assert (row.builtin_version, row.builtin_hash) == (
        1,
        definitions_hash(zfs["check_definitions"], zfs["alert_definitions"]),
    )
    assert row.to_dict()["builtinEdited"] is False


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
