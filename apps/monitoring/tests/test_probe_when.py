# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A rule's condition on a sibling's result in the push path (R-1638): a probe check whose
rule's `when` names another check of its module reads that check's stored result at the
same server and instance; whatever cannot tell lets the rule rate."""

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


@pytest.mark.parametrize(
    ("queue_id", "mail_id", "status"),
    [
        # The sibling is rated first: its result of this report counts.
        ("chk-2", "chk-1", "ok"),
        # The sibling is rated after: it has no stored result yet, the rule rates.
        ("chk-1", "chk-2", "warning"),
    ],
)
def test_the_siblings_result_counts_in_the_evaluation_order(client_db, queue_id, mail_id, status):
    client, factory = client_db
    _add(factory, queue_id, _QUEUE, key="queue")
    _add(factory, mail_id, _MAIL, key="mail")

    _push(client, {queue_id: _result({"queue": 50}), mail_id: _result({"ok": False})})

    assert _rated(factory, queue_id)[0] == status


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


@pytest.mark.parametrize(
    "rules",
    [
        [],
        None,
        "garbage",
        [{"field": "queue", "op": "gt", "value": 10}],
        [{"field": "queue", "op": "gt", "value": 10, "when": {**_WHEN, "check": None}}],
        [{"field": "queue", "op": "gt", "value": 10, "when": "mail"}],
    ],
)
def test_without_a_condition_on_a_sibling_nothing_is_read(rules):
    check = MonitorCheck(id="chk-queue", server_id="srv-1", module_id="test", module_check_key="q")
    assert agent._probe_siblings(_NoQuery(), check, rules) is None
