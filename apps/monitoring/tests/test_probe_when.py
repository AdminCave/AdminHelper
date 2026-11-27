# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A condition on a sibling's result in the push path (R-1638, R-1825): a probe check whose
own or rule's `when` names another check of its module reads that check's stored result at
the same server and instance, rated before it in the same report; whatever cannot tell lets
the check rate."""

import json
import time

import pytest

from app.models import MonitorCheck, MonitorState
from app.routers import agent

_TARGET = {"kind": "port", "port_hint": 8000, "scheme": "http"}
_MAIL = {"sensor": "http", "target": _TARGET, "interval_s": 300, "fields": ["ok"], "rules": []}
_WHEN = {"field": "ok", "op": "eq", "value": True, "check": "mail"}
_QUEUE = {
    "sensor": "http",
    "target": _TARGET,
    "interval_s": 300,
    "fields": ["queue"],
    "rules": [{"field": "queue", "op": "gt", "value": 10, "level": "warning", "when": _WHEN}],
}


def _add(factory, check_id, config, *, key, server_id="srv-1", instance=None, module_id="test"):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id=server_id,
                name=check_id,
                check_type="probe",
                config=json.dumps(config),
                enabled=True,
                consecutive_fails=1,
                consecutive_oks=1,
                module_id=module_id,
                module_instance=instance,
                module_check_key=key,
            )
        )
        db.commit()


def _store(factory, check_id, details):
    """A sibling's stored result, as its last push left it."""
    with factory() as db:
        db.add(MonitorState(check_id=check_id, status="ok", details=details))
        db.commit()


def _mail_said(ok, age=60):
    return json.dumps({"values": {"ok": ok}, "measured_ts": int(time.time()) - age})


def _result(values):
    return {
        "ts": int(time.time()),
        "duration_ms": 12,
        "status": "ok",
        "values": values,
        "error": "",
    }


def _push(client, probes):
    r = client.post("/agent/srv-1/report", json={"probes": probes})
    assert r.status_code == 200, r.text


def _rated(factory, check_id):
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id=check_id).one()
        return state.status, json.loads(state.details)["resting"]


def _said(factory, check_id):
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id=check_id).one()
        return state.status, state.message


def _queue_rated(client, factory, check_id="chk-queue"):
    _push(client, {check_id: _result({"queue": 50})})
    return _rated(factory, check_id)


def test_a_rule_rests_while_the_siblings_stored_result_fails_its_condition(client_db):
    client, factory = client_db
    _add(factory, "chk-queue", _QUEUE, key="queue")
    _add(factory, "chk-mail", _MAIL, key="mail")
    _push(client, {"chk-mail": _result({"ok": False})})

    assert _queue_rated(client, factory) == ("ok", [{"key": "queue.warning", "when": _WHEN}])

    _push(client, {"chk-mail": _result({"ok": True})})
    assert _queue_rated(client, factory) == ("warning", [])


@pytest.mark.parametrize(("queue_id", "mail_id"), [("chk-2", "chk-1"), ("chk-1", "chk-2")])
def test_the_siblings_result_of_the_same_report_counts_whatever_the_ids(
    client_db, queue_id, mail_id
):
    client, factory = client_db
    _add(factory, queue_id, _QUEUE, key="queue")
    _add(factory, mail_id, _MAIL, key="mail")

    _push(client, {queue_id: _result({"queue": 50}), mail_id: _result({"ok": False})})

    assert _rated(factory, queue_id) == ("ok", [{"key": "queue.warning", "when": _WHEN}])


def test_without_the_sibling_the_rule_rates(client_db):
    client, factory = client_db
    _add(factory, "chk-queue", _QUEUE, key="queue")
    assert _queue_rated(client, factory) == ("warning", [])


# Each case builds its result when it runs: built at collection, a result ages with the suite
# before the case is reached and the fresh one crosses the bound.
@pytest.mark.parametrize(
    ("details", "status"),
    [
        (lambda: _mail_said(False, age=840), "ok"),
        # Older than two of its intervals and an agent run (900 s): the sibling has stopped.
        (lambda: _mail_said(False, age=960), "warning"),
        (lambda: None, "warning"),
        (lambda: "not json", "warning"),
        (lambda: json.dumps({"values": {"ok": False}}), "warning"),
    ],
    ids=["fresh", "stopped", "none", "not-json", "no-time"],
)
def test_a_sibling_counts_only_with_a_fresh_result(client_db, details, status):
    client, factory = client_db
    _add(factory, "chk-queue", _QUEUE, key="queue")
    _add(factory, "chk-mail", _MAIL, key="mail")
    _store(factory, "chk-mail", details())
    assert _queue_rated(client, factory)[0] == status


@pytest.mark.parametrize(
    ("sibling", "status"),
    [
        ({}, "ok"),
        ({"instance": "b"}, "warning"),
        ({"server_id": "srv-2"}, "warning"),
        ({"module_id": "other"}, "warning"),
        ({"key": "backup"}, "warning"),
    ],
)
def test_only_the_sibling_of_the_same_server_module_and_instance_counts(client_db, sibling, status):
    client, factory = client_db
    _add(factory, "chk-queue", _QUEUE, key="queue", instance="a")
    _add(factory, "chk-mail", _MAIL, **{"key": "mail", "instance": "a", **sibling})
    _store(factory, "chk-mail", _mail_said(False))
    assert _queue_rated(client, factory)[0] == status


def test_a_check_from_before_modules_reads_no_sibling(client_db):
    client, factory = client_db
    _add(factory, "chk-queue", _QUEUE, key=None, module_id=None)
    _add(factory, "chk-mail", _MAIL, key="mail", module_id=None)
    _store(factory, "chk-mail", _mail_said(False))
    assert _queue_rated(client, factory)[0] == "warning"


class _NoQuery:
    def query(self, *args):
        raise AssertionError("no query expected")


_RULE = {"field": "queue", "op": "gt", "value": 10}


@pytest.mark.parametrize(
    "config",
    [
        {"rules": []},
        {"rules": None},
        {"rules": "garbage"},
        {"rules": [_RULE]},
        {"rules": [{**_RULE, "when": {**_WHEN, "check": None}}]},
        {"rules": [{**_RULE, "when": "mail"}]},
        {"rules": [_RULE], "when": None},
        {"rules": [_RULE], "when": "mail"},
        {"rules": [_RULE], "when": {**_WHEN, "check": None}},
        {"rules": [_RULE], "when": {**_WHEN, "check": 5}},
        [],
        None,
    ],
)
def test_without_a_condition_on_a_sibling_nothing_is_read(config):
    check = MonitorCheck(id="chk-queue", server_id="srv-1", module_id="test", module_check_key="q")
    assert agent._probe_siblings(_NoQuery(), check, config) is None


def test_the_siblings_come_from_the_checks_and_the_rules_conditions():
    config = {
        "rules": [{**_RULE, "when": _WHEN}, {**_RULE, "when": {**_WHEN, "check": "aio"}}, "x"],
        "when": {**_WHEN, "check": "aio"},
    }
    assert agent._sibling_names(config) == ["aio", "mail"]
    assert agent._sibling_names({"when": {**_WHEN, "check": "backup"}}) == ["backup"]


# --- the check rests as a whole (R-1825) ---

_STATUS = {
    "sensor": "http",
    "target": _TARGET,
    "interval_s": 300,
    "fields": ["status_code"],
    "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
    "when": _WHEN,
}
_REFUSED = {"ts": 0, "duration_ms": 3, "status": "error", "values": {}, "error": "refused"}


def _refused():
    return {**_REFUSED, "ts": int(time.time())}


@pytest.mark.parametrize(("status_id", "mail_id"), [("chk-2", "chk-1"), ("chk-1", "chk-2")])
def test_a_check_rests_on_its_siblings_result_of_the_same_report(client_db, status_id, mail_id):
    client, factory = client_db
    _add(factory, status_id, _STATUS, key="status")
    _add(factory, mail_id, _MAIL, key="mail")

    _push(client, {status_id: _refused(), mail_id: _result({"ok": False})})
    assert _said(factory, status_id) == ("ok", "Resting (mail.ok = false): Probe failed: refused")

    _push(client, {status_id: _refused(), mail_id: _result({"ok": True})})
    assert _said(factory, status_id) == ("critical", "Probe failed: refused")


def test_a_check_rests_on_its_siblings_stored_result(client_db):
    client, factory = client_db
    _add(factory, "chk-status", _STATUS, key="status")
    _add(factory, "chk-mail", _MAIL, key="mail")
    _store(factory, "chk-mail", _mail_said(False))

    _push(client, {"chk-status": _result({"status_code": 503})})

    assert _said(factory, "chk-status") == (
        "ok",
        "Resting (mail.ok = false): OK: status_code = 503",
    )
    assert _rated(factory, "chk-status")[1] == [{"key": "status_code.critical", "when": _WHEN}]


@pytest.mark.parametrize(
    "details",
    [lambda: None, lambda: _mail_said(False, age=960)],
    ids=["none", "stopped"],
)
def test_without_a_fresh_sibling_the_check_rates(client_db, details):
    client, factory = client_db
    _add(factory, "chk-status", _STATUS, key="status")
    _add(factory, "chk-mail", _MAIL, key="mail")
    _store(factory, "chk-mail", details())

    _push(client, {"chk-status": _refused()})

    assert _said(factory, "chk-status") == ("critical", "Probe failed: refused")


def _check(check_id, config, check_type="probe"):
    raw = config if isinstance(config, str) or config is None else json.dumps(config)
    return MonitorCheck(id=check_id, server_id="srv-1", check_type=check_type, config=raw)


def test_the_checks_that_name_a_sibling_are_rated_last_each_group_by_id():
    checks = [
        _check("chk-1", _STATUS),
        _check("chk-2", _MAIL),
        # Another type is never a probe's sibling, whatever its config holds.
        _check("chk-3", {"when": _WHEN}, check_type="agent_resources"),
        # Rated with the first group: the evaluation reports the broken config as before.
        _check("chk-4", "not json"),
        _check("chk-5", _QUEUE),
        _check("chk-6", None),
        _check("chk-7", ["not", "a", "dict"]),
        _check("chk-8", "[" * 100_000),
    ]

    order = [check.id for check in agent._in_rating_order(checks)]

    assert order == ["chk-2", "chk-3", "chk-4", "chk-6", "chk-7", "chk-8", "chk-1", "chk-5"]
