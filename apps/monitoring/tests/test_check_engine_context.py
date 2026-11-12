# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""execute_check hands a checker with `wants_context` its previous details and the state
of its partner check (R-1224, the path diagnosis); every other checker runs as before."""

import datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.check_engine as ce
import app.core.database as database_mod
from app.checkers import CheckContext, PartnerState
from app.models import Base, MonitorCheck, MonitorState

SEEN = datetime.datetime(2026, 11, 12, 6, 0, 0)


def _factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
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
    """c1 (central, paired with p1 on server s1) and the partner p1 as `partner` overrides."""
    spec = {"server_id": "s1", "check_type": "probe", "config": {"sensor": "certfile"}}
    spec.update(partner or {})
    with factory() as db:
        _add_check(db, "c1", config={"sensor": "tls", "pair_check_id": "p1"})
        _add_state(db, "c1", details=own_details)
        _add_check(db, "p1", **spec)
        if partner_state:
            _add_state(db, "p1", status="critical", details=json.dumps({"values": {"days": 3}}))
        db.commit()


def test_previous_details_and_partner_arrive(monkeypatch):
    factory = _factory()
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


def test_a_partner_without_a_state_is_pending(monkeypatch):
    factory = _factory()
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
    ],
    ids=["other-server", "no-server", "not-probe", "disabled"],
)
def test_a_partner_that_does_not_qualify_is_none(monkeypatch, partner):
    factory = _factory()
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
def test_a_missing_or_malformed_pair_id_means_no_partner(monkeypatch, pair_check_id):
    factory = _factory()
    with factory() as db:
        _add_check(db, "c1", config={"sensor": "tls", "pair_check_id": pair_check_id})
        _add_check(db, "p1", check_type="probe", config={"sensor": "tls"})
        _add_state(db, "p1")
        db.commit()
    checker = _ContextChecker()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert checker.contexts == [CheckContext()]


def test_a_central_check_without_a_server_has_no_partner(monkeypatch):
    # Both without a server_id: None == None is no proof of the same server.
    factory = _factory()
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
def test_unreadable_stored_json_degrades_to_none(monkeypatch, own, partner_details, partner_config):
    factory = _factory()
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
def test_other_checkers_get_no_context(monkeypatch, wants_context):
    # Only a literal True opts in: a checker that does not ask runs exactly as before.
    factory = _factory()
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


def test_a_checker_without_the_attribute_runs_plain(monkeypatch):
    factory = _factory()
    _seed_pair(factory)
    calls = []
    _wire(
        monkeypatch,
        factory,
        SimpleNamespace(run=lambda cfg: calls.append(cfg) or ("ok", "m", None)),
    )

    ce.execute_check("c1")

    assert len(calls) == 1


def test_a_failing_context_run_is_unknown(monkeypatch):
    factory = _factory()
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


@pytest.fixture()
def file_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'monitor.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_run_with_context_holds_no_pooled_connection(monkeypatch, file_engine):
    factory = sessionmaker(bind=file_engine)
    _seed_pair(factory, own_details=json.dumps({"k": 1}))
    held = []

    class Counting(_ContextChecker):
        def run_with_context(self, config, context):
            held.append(file_engine.pool.checkedout())
            return super().run_with_context(config, context)

    checker = Counting()
    _wire(monkeypatch, factory, checker)

    ce.execute_check("c1")

    assert held == [0]
    assert checker.contexts[0].prev_details == {"k": 1}
    assert checker.contexts[0].partner.status == "critical"
