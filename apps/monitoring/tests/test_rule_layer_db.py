# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The rule layer of a module's probe check in the database (R-1638): the catalog rules the
check is bound to and the admin's overrides over them. Adopting writes it; at start-up
record_rule_layers gives the checks from before it theirs. A check whose rules are the
catalog's takes them as its catalog; one whose rules the admin changed becomes catalog and
overrides when that gives its rules exactly, so it rates as before; any other stays frozen
as the admin built it."""

import json
import logging

import pytest
from sqlalchemy.orm import sessionmaker

from app import module_sync
from app.catalog.loader import load_catalog
from app.catalog.modules.port import MODULE as PORT_MODULE
from app.checkers.probe import _rate
from app.models import MonitorCheck
from app.module_sync import adopt, definition_hash, record_rule_layers, sync_catalog
from app.rule_layer import convert, effective, read_layer, store_layer
from app.template_sync import read_overrides

from .test_module_sync import (
    BROKER,
    NGINX,
    NOW,
    SCHED,
    SITE,
    SITE_SUMMARY,
    WEB,
    _checks,
    _finding,
    _inventory,
    _paperless,
)

STATUS = {"field": "status_code", "op": "ne", "value": 200, "level": "critical"}
SLOW = {"field": "duration_ms", "op": "gt", "value": 2000, "level": "warning"}
TWO_RULES = {**WEB, "fields": ["status_code", "duration_ms"], "rules": [STATUS, SLOW]}
CATALOG = load_catalog([_paperless(TWO_RULES, BROKER, SCHED), NGINX, ("port", PORT_MODULE)])
# An update since raised the limit.
RAISED = load_catalog(
    [
        _paperless({**TWO_RULES, "rules": [STATUS, {**SLOW, "value": 3000}]}, BROKER, SCHED),
        NGINX,
        ("port", PORT_MODULE),
    ]
)
WITHOUT_PAPERLESS = load_catalog([NGINX, ("port", PORT_MODULE)])
CHANGED = [STATUS, {**SLOW, "value": 5000}]

# Results around every limit of the rules here, and one without a value.
RESULTS = [
    {"status_code": 200, "duration_ms": 100},
    {"status_code": 200, "duration_ms": 2500},
    {"status_code": 200, "duration_ms": 6000},
    {"status_code": 204, "duration_ms": 100},
    {"status_code": 500, "duration_ms": 6000},
    {"status_code": 200},
]


def test_the_test_catalogs_are_valid():
    catalogs = (CATALOG, RAISED, WITHOUT_PAPERLESS)
    assert [c.errors for c in catalogs] == [()] * len(catalogs)


@pytest.fixture()
def db(db_engine):
    session = sessionmaker(bind=db_engine)()
    yield session
    session.close()


@pytest.fixture()
def actions(monkeypatch):
    seen = []
    monkeypatch.setattr(module_sync, "apply_scheduler_actions", seen.extend)
    return seen


@pytest.fixture()
def logs(caplog):
    caplog.set_level(logging.DEBUG, logger="app.module_sync")
    return caplog


def _catalog_rules(catalog):
    check = next(c for c in catalog.modules["paperless"].checks if c.key == "web")
    return [rule.model_dump() for rule in check.rules]


def _rules(row):
    return json.loads(row.config)["rules"]


def _before_the_layer(db, actions, *, rules=None, marked=False):
    """The web check as a version before the layer left it: no layer, its rules in its
    config, the mark "config" when the admin changed them. Its broker sibling has no
    rules and no layer either."""
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=CATALOG, now=NOW)
    actions.clear()
    rows = _checks(db, finding)
    for row in rows.values():
        row.rule_layer = None
        row.overridden_fields = "[]"
    web = rows["web"]
    if rules is not None:
        config = json.loads(web.config)
        config["rules"] = rules
        web.config = json.dumps(config)
    if marked:
        web.overridden_fields = json.dumps(["config"])
    db.commit()
    return web


def _ratings(rules):
    return [_rate(rules, values, None, 1000.0) for values in RESULTS]


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "not json",
        "[]",
        json.dumps({"catalog": {}, "overrides": {}, "conflicts": []}),
        json.dumps({"catalog": [], "overrides": [], "conflicts": []}),
        json.dumps({"catalog": [], "overrides": {}}),
    ],
)
def test_a_column_without_a_layer_reads_as_none(stored):
    assert read_layer(MonitorCheck(rule_layer=stored)) is None


def test_storing_a_layer_writes_the_rules_it_gives_and_the_mark_while_overrides_stand():
    catalog = _catalog_rules(CATALOG)
    row = MonitorCheck(
        config=json.dumps({"sensor": "http", "rules": []}),
        overridden_fields=json.dumps(["enabled"]),
    )

    store_layer(row, catalog, {"duration_ms.warning": {"value": 5000}}, [{"key": "k"}])

    assert json.loads(row.config) == {
        "sensor": "http",
        "rules": [catalog[0], {**catalog[1], "value": 5000}],
    }
    assert read_layer(row) == {
        "catalog": catalog,
        "overrides": {"duration_ms.warning": {"value": 5000}},
        "conflicts": [{"key": "k"}],
    }
    assert json.loads(row.overridden_fields) == ["config", "enabled"]

    # An override that says what the catalog says is none.
    store_layer(row, catalog, {"duration_ms.warning": {"value": 2000}})

    assert read_layer(row)["overrides"] == {}
    assert _rules(row) == catalog
    assert json.loads(row.overridden_fields) == ["enabled"]


def test_adopting_gives_the_checks_their_layer(db, actions):
    _inventory(db)
    finding = _finding(db)
    adopt(db, finding.id, catalog=CATALOG, now=NOW)

    rows = _checks(db, finding)
    web = rows["web"]
    assert read_layer(web) == {
        "catalog": _catalog_rules(CATALOG),
        "overrides": {},
        "conflicts": [],
    }
    assert _rules(web) == _catalog_rules(CATALOG)
    assert read_overrides(web) == set()
    assert read_layer(rows["broker"]) == {"catalog": [], "overrides": {}, "conflicts": []}
    # Nothing left for the start-up.
    assert record_rule_layers(db, catalog=CATALOG) == (0, 0, 0)


def test_adopting_a_vhost_gives_its_probe_check_a_layer_and_its_central_ones_none(db, actions):
    finding = _finding(db, "site", "shop.example.org", summary=SITE_SUMMARY)
    adopt(db, finding.id, catalog=SITE, now=NOW)

    layers = {key: read_layer(row) for key, row in _checks(db, finding).items()}
    assert layers == {
        "served": {"catalog": [], "overrides": {}, "conflicts": []},
        "resolves": None,
        "outside": None,
    }


@pytest.mark.parametrize("today", [CATALOG, RAISED])
def test_a_check_with_the_catalogs_rules_takes_its_stored_rules_as_its_catalog(db, actions, today):
    # With an update pending, the check is still bound to the rules it has.
    web = _before_the_layer(db, actions)
    before = _rules(web)

    assert record_rule_layers(db, catalog=today) == (2, 0, 0)
    db.rollback()  # what it recorded is committed

    assert read_layer(web) == {"catalog": before, "overrides": {}, "conflicts": []}
    assert _rules(web) == before == _catalog_rules(CATALOG)
    assert read_overrides(web) == set()


@pytest.mark.parametrize(
    ("rules", "overrides"),
    [
        (CHANGED, {"duration_ms.warning": {"value": 5000}}),
        ([STATUS, {**SLOW, "level": "critical"}], {"duration_ms.warning": {"level": "critical"}}),
        ([STATUS], {"duration_ms.warning": {"enabled": False}}),
        (
            [{**STATUS, "value": 204}, {**SLOW, "value": 5000, "level": "critical"}],
            {
                "status_code.critical": {"value": 204},
                "duration_ms.warning": {"value": 5000, "level": "critical"},
            },
        ),
    ],
    ids=["value", "level", "switched-off", "several"],
)
def test_rules_the_admin_changed_become_catalog_and_overrides(db, actions, rules, overrides):
    web = _before_the_layer(db, actions, rules=rules, marked=True)

    assert record_rule_layers(db, catalog=CATALOG) == (1, 1, 0)

    layer = read_layer(web)
    assert (layer["catalog"], layer["overrides"], layer["conflicts"]) == (
        _catalog_rules(CATALOG),
        overrides,
        [],
    )
    assert _rules(web) == effective(_catalog_rules(CATALOG), overrides)
    assert _ratings(_rules(web)) == _ratings(rules)
    assert read_overrides(web) == {"config"}
    # Once converted, a check stays as it is.
    stored = (web.config, web.rule_layer)
    assert record_rule_layers(db, catalog=CATALOG) == (0, 0, 0)
    assert (web.config, web.rule_layer) == stored


def test_a_level_change_keeps_the_key_of_the_catalog_rule(db, actions):
    web = _before_the_layer(db, actions, rules=[STATUS, {**SLOW, "level": "critical"}], marked=True)

    record_rule_layers(db, catalog=CATALOG)

    assert _rules(web)[1] == {**SLOW, "level": "critical", "key": "duration_ms.warning"}


def test_changed_rules_that_are_the_catalogs_again_lose_the_mark(db, actions):
    web = _before_the_layer(db, actions, rules=[STATUS, SLOW], marked=True)

    assert record_rule_layers(db, catalog=CATALOG) == (1, 1, 0)

    assert read_layer(web)["overrides"] == {}
    assert read_overrides(web) == set()


@pytest.mark.parametrize(
    ("rules", "today", "why"),
    [
        (CHANGED, RAISED, "it is bound to another definition than today's"),
        (CHANGED, WITHOUT_PAPERLESS, "the catalog has no such check"),
        (
            [*CHANGED, {"field": "duration_ms", "op": "gt", "value": 9000, "level": "critical"}],
            CATALOG,
            "with op 'gt' is no catalog rule",
        ),
        ([{**STATUS, "op": "eq", "value": 500}, SLOW], CATALOG, "with op 'eq' is no catalog rule"),
        ([SLOW, STATUS], CATALOG, "in another order or form"),
        ([STATUS, STATUS], CATALOG, "is given twice"),
        ("garbage", CATALOG, "its rules cannot be read"),
    ],
    ids=[
        "other-definition",
        "module-gone",
        "added-rule",
        "op-changed",
        "reordered",
        "twice",
        "unreadable",
    ],
)
def test_rules_the_admin_changed_otherwise_stay_frozen(db, actions, logs, rules, today, why):
    web = _before_the_layer(db, actions, rules=rules, marked=True)
    before = web.config
    logs.clear()

    assert record_rule_layers(db, catalog=today) == (1, 0, 1)

    assert web.rule_layer is None
    assert web.config == before
    assert read_overrides(web) == {"config"}
    rows = [r.getMessage() for r in logs.records if r.getMessage().startswith("Module check ")]
    assert len(rows) == 1
    assert rows[0].startswith(f"Module check {web.id} keeps the admin's rules frozen: ")
    assert why in rows[0]
    # Looked at again at the next start, and left as it is.
    assert record_rule_layers(db, catalog=today) == (0, 0, 1)
    assert (web.rule_layer, web.config) == (None, before)


def test_a_frozen_check_without_a_hash_stays_frozen_after_the_sync(db, actions):
    # Nothing shows the definition the admin changed the rules from: the sync gives the
    # check no hash, so a later start does not convert it against today's definition.
    web = _before_the_layer(db, actions, rules=CHANGED, marked=True)
    web.module_check_hash = None
    db.commit()

    assert record_rule_layers(db, catalog=CATALOG) == (1, 0, 1)
    assert sync_catalog(db, catalog=CATALOG) == 0

    assert web.module_check_hash is None
    assert record_rule_layers(db, catalog=CATALOG) == (0, 0, 1)
    assert web.rule_layer is None


def test_an_unmarked_check_without_a_hash_gets_its_layer_and_the_sync_its_hash(db, actions):
    web = _before_the_layer(db, actions)
    web.module_check_hash = None
    db.commit()

    assert record_rule_layers(db, catalog=CATALOG) == (2, 0, 0)
    sync_catalog(db, catalog=CATALOG)

    assert read_layer(web)["catalog"] == _catalog_rules(CATALOG)
    assert web.module_check_hash == definition_hash(
        next(c for c in CATALOG.modules["paperless"].checks if c.key == "web")
    )


@pytest.mark.parametrize(
    ("marked", "stored", "counts", "overrides"),
    [
        (False, [{**STATUS, "if_absent": None}, {**SLOW, "unless": None}], (2, 0, 0), {}),
        (
            True,
            [{**STATUS, "if_absent": None}, {**SLOW, "value": 5000, "unless": None}],
            (1, 1, 0),
            {"duration_ms.warning": {"value": 5000}},
        ),
    ],
    ids=["unchanged", "changed"],
)
def test_stored_rules_count_in_the_form_the_catalog_dumps_them(
    db, actions, marked, stored, counts, overrides
):
    """A part stored as null is a part not set, as in a catalog rule."""
    web = _before_the_layer(db, actions, rules=stored, marked=marked)

    assert record_rule_layers(db, catalog=CATALOG) == counts

    assert read_layer(web) == {
        "catalog": _catalog_rules(CATALOG),
        "overrides": overrides,
        "conflicts": [],
    }
    assert _rules(web) == effective(_catalog_rules(CATALOG), overrides)


def test_a_catalog_rule_with_its_own_key_converts_with_that_key():
    catalog = [STATUS, {**SLOW, "key": "slow"}]

    assert convert(catalog, [STATUS, {**SLOW, "key": "slow", "value": 5000}]) == (
        {"slow": {"value": 5000}},
        None,
    )
    assert convert(catalog, [STATUS, {**SLOW, "key": "slow", "level": "critical"}]) == (
        {"slow": {"level": "critical"}},
        None,
    )


def test_a_check_the_admin_changed_over_its_layer_still_gets_its_hash(db, actions):
    web = _before_the_layer(db, actions)
    web.module_check_hash = None
    db.commit()
    record_rule_layers(db, catalog=CATALOG)
    store_layer(web, _catalog_rules(CATALOG), {"duration_ms.warning": {"value": 5000}})
    db.commit()

    sync_catalog(db, catalog=CATALOG)

    assert web.module_check_hash == definition_hash(
        next(c for c in CATALOG.modules["paperless"].checks if c.key == "web")
    )
    assert _rules(web) == CHANGED


@pytest.mark.parametrize(
    "rules",
    ["garbage", [STATUS, STATUS], [{"field": "status_code"}]],
    ids=["not-a-list", "twice", "no-rule"],
)
def test_an_unmarked_check_with_rules_that_do_not_hold_keeps_no_layer(db, actions, logs, rules):
    web = _before_the_layer(db, actions, rules=rules)
    before = web.config
    logs.clear()

    assert record_rule_layers(db, catalog=CATALOG) == (1, 0, 0)

    assert (web.rule_layer, web.config) == (None, before)
    warnings = [r for r in logs.records if r.levelno == logging.WARNING]
    assert [r.getMessage().split(":")[0] for r in warnings] == [
        f"Module check {web.id} keeps no rule layer"
    ]


def test_only_the_probe_checks_of_modules_get_a_layer(db):
    config = json.dumps({"rules": [STATUS]})
    db.add_all(
        [
            MonitorCheck(id="manual", name="Manual", check_type="probe", config=config),
            MonitorCheck(
                id="central",
                name="Central",
                check_type="central",
                config=config,
                module_id="paperless",
                module_instance="paperless",
                module_check_key="web",
            ),
        ]
    )
    db.commit()

    assert record_rule_layers(db, catalog=CATALOG) == (0, 0, 0)

    assert [row.rule_layer for row in db.query(MonitorCheck).order_by(MonitorCheck.id)] == [
        None,
        None,
    ]


def test_the_log_counts_what_the_start_did(db, actions, logs):
    _before_the_layer(db, actions, rules=CHANGED, marked=True)

    record_rule_layers(db, catalog=CATALOG)
    record_rule_layers(db, catalog=CATALOG)

    counts = [r.getMessage() for r in logs.records if r.getMessage().startswith("Rule layers:")]
    # The second start has nothing left to do and says nothing.
    assert counts == ["Rule layers: 1 recorded, 1 converted, 0 frozen (the admin's rules stay)"]
