# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""execute_check hands a checker with `wants_context` its previous details and the state
of its partner check (R-1224, the path diagnosis); every other checker runs as before."""

import datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

import app.check_engine as ce
import app.core.database as database_mod
from app.central.limits import SKIPPED_BUSY_MESSAGE, SKIPPED_SPACING_MESSAGE, RunSkipped
from app.checkers import CheckContext, PartnerState
from app.checkers.context import DiskRules
from app.models import MonitorCheck, MonitorState

from ._helpers import no_rating, standing_skip

SEEN = datetime.datetime(2026, 11, 12, 6, 0, 0)


def _factory(engine):
    return sessionmaker(bind=engine)


def _add_check(db, check_id, *, server_id="s1", check_type="central", config=None, enabled=True):
    db.add(
        MonitorCheck(
            id=check_id,
            server_id=server_id,
            name=check_id,
            check_type=check_type,
            config=config if isinstance(config, str) else json.dumps(config or {}),
            enabled=enabled,
            consecutive_fails=1,
        )
    )


def _add_state(db, check_id, *, status="ok", details=None):
    db.add(
        MonitorState(
            check_id=check_id,
            status=status,
            fail_count=0,
            since=SEEN,
            last_check=SEEN,
            details=details,
        )
    )


class _ContextChecker:
    wants_context = True

    def __init__(self, result=("ok", "fine", None)):
        self.contexts: list[CheckContext] = []
        self.result = result

    def run(self, config):
        raise AssertionError("a checker with wants_context runs with its context")

    def run_with_context(self, config, context):
        self.contexts.append(context)
        return self.result


def _wire(monkeypatch, factory, checker):
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda t: checker)
    monkeypatch.setattr(ce.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))


def _seed_pair(factory, *, partner=None, partner_state=True, own_details=None):
    """c1 (central, paired with p1 on server s1) and the partner p1 as `partner` overrides;
    `skip` puts a skip in force on p1."""
    spec = {"server_id": "s1", "check_type": "probe", "config": {"sensor": "certfile"}}
    spec.update(partner or {})
    skip = spec.pop("skip", False)
    with factory() as db:
        _add_check(db, "c1", config={"sensor": "tls", "pair_check_id": "p1"})
        _add_state(db, "c1", details=own_details)
        _add_check(db, "p1", **spec)
        if skip:
            db.add(standing_skip("p1"))
        if partner_state:
            _add_state(db, "p1", status="critical", details=json.dumps({"values": {"days": 3}}))
        db.commit()


def test_previous_details_and_partner_arrive(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_pair(factory, own_details=json.dumps({"public_since": "2026-11-01T00:00:00"}))
    checker = _ContextChecker(("warning", "renewed", {"_details": {"diagnosis": "x"}}))
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts == [
        CheckContext(
            prev_details={"public_since": "2026-11-01T00:00:00"},
            partner=PartnerState(
                check_id="p1",
                sensor="certfile",
                status="critical",
                details={"values": {"days": 3}},
                last_check=SEEN,
            ),
        )
    ]
    # The result of run_with_context is stored like any other.
    with factory() as db:
        st = db.get(MonitorState, "c1")
        assert (st.status, st.message) == ("warning", "renewed")
        assert json.loads(st.details) == {"diagnosis": "x"}


def test_a_skipped_check_does_not_run(monkeypatch, db_engine):
    # R-1637: a skip in force keeps the scheduler's job from running the check, the
    # column stays on; its state stays as it was.
    factory = _factory(db_engine)
    with factory() as db:
        _add_check(db, "c1")
        _add_state(db, "c1", status="critical")
        db.add(standing_skip("c1"))
        db.commit()
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts == []
    with factory() as db:
        assert (db.get(MonitorState, "c1").status, db.get(MonitorState, "c1").last_check) == (
            "critical",
            SEEN,
        )


def test_a_partner_without_a_state_is_pending(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_pair(factory, partner_state=False)
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts[0].partner == PartnerState("p1", "certfile", "pending", None, None)
    assert checker.contexts[0].prev_details is None


@pytest.mark.parametrize(
    "partner",
    [
        {"server_id": "s2"},  # another server
        {"server_id": None},
        {"check_type": "tcp"},  # not an agent probe
        {"enabled": False},  # its state is stale
        {"skip": True},  # does not run either (R-1637)
    ],
    ids=["other-server", "no-server", "not-probe", "disabled", "skipped"],
)
def test_a_partner_that_does_not_qualify_is_none(monkeypatch, partner, db_engine):
    factory = _factory(db_engine)
    _seed_pair(factory, partner=partner)
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts == [CheckContext(prev_details=None, partner=None)]


@pytest.mark.parametrize(
    "pair_check_id",
    ["nope", "", 5, ["p1"], None],
    ids=["missing", "empty", "int", "list", "null"],
)
def test_a_missing_or_malformed_pair_id_means_no_partner(monkeypatch, pair_check_id, db_engine):
    factory = _factory(db_engine)
    with factory() as db:
        _add_check(db, "c1", config={"sensor": "tls", "pair_check_id": pair_check_id})
        _add_check(db, "p1", check_type="probe", config={"sensor": "tls"})
        _add_state(db, "p1")
        db.commit()
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts == [CheckContext()]


def test_a_central_check_without_a_server_has_no_partner(monkeypatch, db_engine):
    # Both without a server_id: None == None is no proof of the same server.
    factory = _factory(db_engine)
    with factory() as db:
        _add_check(db, "c1", server_id=None, config={"pair_check_id": "p1"})
        _add_check(db, "p1", server_id=None, check_type="probe", config={"sensor": "tls"})
        _add_state(db, "p1")
        db.commit()
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts[0].partner is None


@pytest.mark.parametrize(
    ("own", "partner_details", "partner_config"),
    [
        ("{broken", "{broken", "{broken"),
        ("[1, 2]", '"text"', "[]"),
        ("null", "null", json.dumps({"sensor": 7})),
    ],
    ids=["broken-json", "not-an-object", "null-and-odd-sensor"],
)
def test_unreadable_stored_json_degrades_to_none(
    monkeypatch, own, partner_details, partner_config, db_engine
):
    factory = _factory(db_engine)
    with factory() as db:
        _add_check(db, "c1", config={"pair_check_id": "p1"})
        _add_state(db, "c1", details=own)
        _add_check(db, "p1", check_type="probe", config=partner_config)
        _add_state(db, "p1", details=partner_details)
        db.commit()
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts == [
        CheckContext(
            prev_details=None,
            partner=PartnerState("p1", None, "ok", None, SEEN),
        )
    ]


@pytest.mark.parametrize("wants_context", [False, None, "yes", 1])
def test_other_checkers_get_no_context(monkeypatch, wants_context, db_engine):
    # Only a literal True opts in: a checker that does not ask runs exactly as before.
    factory = _factory(db_engine)
    _seed_pair(factory)
    calls = []

    def must_not_run(config, context):
        raise AssertionError("run_with_context called")

    checker = SimpleNamespace(
        wants_context=wants_context,
        run=lambda cfg: calls.append(cfg) or ("ok", "plain", None),
        run_with_context=must_not_run,
    )
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert calls == [{"sensor": "tls", "pair_check_id": "p1"}]
    with factory() as db:
        assert db.get(MonitorState, "c1").message == "plain"


def test_a_checker_without_the_attribute_runs_plain(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_pair(factory)
    calls = []
    _wire(
        monkeypatch,
        factory,
        SimpleNamespace(run=lambda cfg: calls.append(cfg) or ("ok", "m", None)),
    )

    ce.execute_check("c1")

    assert len(calls) == 1


def test_a_failing_context_run_is_unknown(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_pair(factory)

    class Boom(_ContextChecker):
        def run_with_context(self, config, context):
            raise RuntimeError("bad")

    _wire(monkeypatch, factory, Boom())

    ce.execute_check("c1")

    with factory() as db:
        st = db.get(MonitorState, "c1")
        assert (st.status, st.message) == ("unknown", "Unexpected error: bad")


# --- R-0615: the context is read before the rollback, no connection during the run ---


def test_run_with_context_holds_no_pooled_connection(monkeypatch, pooled_engine):
    factory = sessionmaker(bind=pooled_engine)
    _seed_pair(factory, own_details=json.dumps({"k": 1}))
    held = []

    class Counting(_ContextChecker):
        def run_with_context(self, config, context):
            held.append(pooled_engine.pool.checkedout())
            return super().run_with_context(config, context)

    checker = Counting()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert held == [0]
    assert checker.contexts[0].prev_details == {"k": 1}
    assert checker.contexts[0].partner.status == "critical"


# --- a stored config that is no mapping, a skipped run (R-1224 T3) ---


class _Refusing(_ContextChecker):
    def run_with_context(self, config, context):
        raise AssertionError("a corrupt config never reaches the checker")


@pytest.mark.parametrize("stored", ["[1, 2]", "42", '"tls"', "null"])
def test_a_config_that_is_no_mapping_is_an_invalid_configuration(monkeypatch, stored, db_engine):
    factory = _factory(db_engine)
    with factory() as db:
        _add_check(db, "c1", config=stored)
        db.commit()
    _wire(monkeypatch, factory, _Refusing())

    ce.execute_check("c1")

    with factory() as db:
        st = db.get(MonitorState, "c1")
        assert (st.status, st.message) == ("unknown", "Invalid check configuration")


class _Skipping(_ContextChecker):
    def __init__(self, note):
        super().__init__()
        self.note = note

    def run_with_context(self, config, context):
        raise RunSkipped(self.note)


def _seed_skip(factory, message, *, state=True):
    with factory() as db:
        _add_check(db, "c1", config={"sensor": "tls", "host": "www.example.test"})
        if state:
            db.add(
                MonitorState(
                    check_id="c1",
                    status="warning",
                    fail_count=2,
                    since=SEEN,
                    last_check=SEEN,
                    message=message,
                    details=json.dumps({"public_since": "2026-11-01T00:00:00Z"}),
                )
            )
        db.commit()


def _skip(monkeypatch, factory, note):
    written, alerted = [], []
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda t: _Skipping(note))
    monkeypatch.setattr(ce.victoria, "write_check_result", lambda **kw: written.append(kw))
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: alerted.append(a)))
    ce.execute_check("c1")
    return written, alerted


def test_a_skipped_run_only_notes_itself_behind_the_message(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_skip(factory, "certificate due for renewal")

    written, alerted = _skip(monkeypatch, factory, SKIPPED_SPACING_MESSAGE)

    assert (written, alerted) == ([], [])
    with factory() as db:
        st = db.get(MonitorState, "c1")
        assert st.message == "certificate due for renewal (skipped: minimum spacing)"
        assert (st.status, st.fail_count, st.since, st.last_check) == ("warning", 2, SEEN, SEEN)
        assert json.loads(st.details) == {"public_since": "2026-11-01T00:00:00Z"}


def test_a_second_skip_replaces_the_note_instead_of_stacking(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_skip(factory, "certificate due for renewal (skipped: minimum spacing)")

    _skip(monkeypatch, factory, SKIPPED_BUSY_MESSAGE)

    with factory() as db:
        assert db.get(MonitorState, "c1").message == (
            "certificate due for renewal (skipped: too many central checks at once)"
        )


@pytest.mark.parametrize("message", [None, "", "skipped: minimum spacing"])
def test_a_skip_without_a_result_message_is_the_note_alone(monkeypatch, message, db_engine):
    factory = _factory(db_engine)
    _seed_skip(factory, message)

    _skip(monkeypatch, factory, SKIPPED_BUSY_MESSAGE)

    with factory() as db:
        assert db.get(MonitorState, "c1").message == SKIPPED_BUSY_MESSAGE


def test_the_noted_message_stays_within_the_cap(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_skip(factory, "x" * ce.MAX_MESSAGE)

    _skip(monkeypatch, factory, SKIPPED_SPACING_MESSAGE)

    with factory() as db:
        message = db.get(MonitorState, "c1").message
    assert len(message) == ce.MAX_MESSAGE
    assert message.endswith("… (skipped: minimum spacing)")


def test_a_skip_before_the_first_result_leaves_no_state(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_skip(factory, None, state=False)

    written, alerted = _skip(monkeypatch, factory, SKIPPED_SPACING_MESSAGE)

    assert (written, alerted) == ([], [])
    with factory() as db:
        assert db.get(MonitorState, "c1") is None


def _seed_forecast(factory, *, resources=True, enabled=True, server="s1", skip=False):
    with factory() as db:
        _add_check(db, "f1", check_type="disk_forecast", config={"server_id": "s1"})
        if resources:
            _add_check(
                db,
                "r1",
                server_id=server,
                check_type="agent_resources",
                enabled=enabled,
                config={
                    "ignore_mounts": ["/boot/efi"],
                    "disk_min_free_gb": 10,
                    "disk_overrides": {"/data": {"min_free_gb": 500, "warn": None}, "/x": {}},
                },
            )
            _add_state(
                db,
                "r1",
                details=json.dumps(
                    {
                        "disks": [
                            {"mount": "/", "free_gb": 12.5},
                            {"mount": "/data", "free_gb": None},
                        ]
                    }
                ),
            )
            if skip:
                db.add(standing_skip("r1"))
        db.commit()


def test_disk_forecast_gets_the_disk_rules_of_its_host(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_forecast(factory)
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("f1")

    assert checker.contexts[0].disk_rules == DiskRules(
        ignore_mounts=frozenset({"/boot/efi"}),
        min_free_gb={"/data": 500.0},
        default_min_free_gb=10.0,
        free_gb={"/": 12.5},
    )


@pytest.mark.parametrize(
    "seed", [{"resources": False}, {"enabled": False}, {"skip": True}, {"server": "s2"}]
)
def test_disk_forecast_without_an_enabled_resources_check_of_its_host_has_no_rules(
    monkeypatch, seed, db_engine
):
    factory = _factory(db_engine)
    _seed_forecast(factory, **seed)
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("f1")

    assert checker.contexts[0].disk_rules is None


def test_disk_forecast_rules_take_the_exceptions_of_the_resources_check(monkeypatch, db_engine):
    # Its ignore_mounts masked, its no_rating exceptions in force as they are (R-1637).
    factory = _factory(db_engine)
    _seed_forecast(factory)
    with factory() as db:
        resources = db.get(MonitorCheck, "r1")
        config = {**json.loads(resources.config), "ignore_mounts": ["/boot/efi", "/mnt/[x]"]}
        resources.config = json.dumps(config)
        db.add(no_rating("r1", "/srv/*", kind="mount", id="exc-1"))
        db.add(no_rating("r1", "/old", kind="mount", id="exc-2", ended=True))
        db.commit()
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("f1")

    rules = checker.contexts[0].disk_rules
    assert rules.ignore_mounts == frozenset({"/boot/efi", "/mnt/[[]x]", "/srv/*"})
    mounts = ("/boot/efi", "/mnt/[x]", "/mnt/x", "/srv/a", "/old", "/")
    assert [m for m in mounts if rules.ignores(m)] == ["/boot/efi", "/mnt/[x]", "/srv/a"]
