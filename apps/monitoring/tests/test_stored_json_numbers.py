# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stored JSON columns with numbers no strict JSON reader takes (T5).

Python's json.loads reads NaN, Infinity and integers of any length, and older rows hold such
values: _details from a report, a check config, a free channel_config, a template definition.
The to_dict methods hand them out as null, so every listing stays readable; nothing stored is
rewritten. Rows go straight into the test DB, as they would sit there from before."""

import json
import math

import pytest

from app.builtin_templates import canonical_definitions, definitions_hash, shipped_builtin
from app.models import (
    MonitorAlertRule,
    MonitorCheck,
    MonitorState,
    MonitorTemplate,
    loads_readable,
)

_BIG_INT = "1" + "0" * 399  # an integer with 400 digits, beyond float range


def _seed(factory):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-1",
                server_id="srv-1",
                name="disks",
                check_type="smart_health",
                config='{"reallocated_warn": Infinity}',
                enabled=True,
                interval="5m",
                severity="critical",
            )
        )
        db.add(
            MonitorState(
                check_id="chk-1",
                status="ok",
                message="ok",
                details=(
                    '{"a": NaN, "b": -Infinity, "c": 1e400, "d": '
                    + _BIG_INT
                    + ', "e": 1.5, "f": 7}'
                ),
            )
        )
        db.add(
            MonitorAlertRule(
                id="rule-1",
                name="hook",
                channel="webhook",
                channel_config='{"url": "https://hooks.example.com/x", "retries": NaN}',
            )
        )
        db.add(
            MonitorTemplate(
                id="tpl-1",
                name="Disks",
                check_definitions=(
                    '[{"def_id": "d1", "name": "disks", "check_type": "smart_health",'
                    ' "config": {"reallocated_warn": Infinity}}]'
                ),
                alert_definitions="[]",
            )
        )
        db.commit()


def _reject_constant(token):
    raise ValueError(f"not a JSON number: {token}")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"number out of range: {text[:20]}")
    return value


def _float_range_int(text):
    value = int(text)
    float(value)  # OverflowError beyond float range
    return value


def _strict_loads(text):
    """Reads like serde_json (the desktop): no NaN or Infinity token, and every number has to
    fit a finite f64, an integer beyond float range is "number out of range"."""
    return json.loads(
        text,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        parse_int=_float_range_int,
    )


@pytest.mark.parametrize("path", ["/status", "/checks", "/checks/chk-1", "/alerts", "/templates"])
def test_listing_with_stored_non_finite_numbers_reads_strictly(client_db, path):
    client, factory = client_db
    _seed(factory)

    resp = client.get(path)

    assert resp.status_code == 200
    _strict_loads(resp.text)


def test_check_config_and_details_show_null_for_unreadable_numbers(client_db):
    client, factory = client_db
    _seed(factory)

    body = _strict_loads(client.get("/checks/chk-1").text)

    assert body["config"] == {"reallocated_warn": None}
    details = body["state"]["details"]
    assert details == {"a": None, "b": None, "c": None, "d": None, "e": 1.5, "f": 7}
    assert type(details["f"]) is int


def test_status_shows_the_same_details(client_db):
    client, factory = client_db
    _seed(factory)

    [check] = _strict_loads(client.get("/status").text)

    assert check["config"] == {"reallocated_warn": None}
    assert check["state"]["details"]["d"] is None
    assert check["state"]["details"]["e"] == 1.5


def test_alert_rule_channel_config_shows_null(client_db):
    client, factory = client_db
    _seed(factory)

    [rule] = _strict_loads(client.get("/alerts").text)

    assert rule["channelConfig"] == {"url": "https://hooks.example.com/x", "retries": None}


def test_template_definition_shows_null(client_db):
    client, factory = client_db
    _seed(factory)

    [template] = _strict_loads(client.get("/templates").text)

    assert template["checkDefinitions"][0]["config"] == {"reallocated_warn": None}


@pytest.mark.parametrize("token", ["Infinity", "-Infinity", "NaN", "1e400", _BIG_INT])
def test_builtin_update_comparison_shows_null(client_db, token):
    """The update comparison of a standard template reads its stored definitions like to_dict;
    the shipped side comes from the code and stays as it is."""
    client, factory = client_db
    shipped = shipped_builtin("zfs-storage")
    stored = json.dumps(shipped["check_definitions"]).replace(
        '"capacity_warn": 80', '"capacity_warn": ' + token
    )
    assert '"capacity_warn": ' + token in stored
    with factory() as db:
        db.add(
            MonitorTemplate(
                id="tpl-zfs",
                name=shipped["name"],
                builtin_slug="zfs-storage",
                builtin_version=shipped["version"],
                builtin_hash=definitions_hash(
                    shipped["check_definitions"], shipped["alert_definitions"]
                ),
                check_definitions=stored,
                alert_definitions="[]",
            )
        )
        db.commit()

    resp = client.get("/templates/tpl-zfs/builtin-update")

    assert resp.status_code == 200
    body = _strict_loads(resp.text)
    [current] = body["current"]["checkDefinitions"]
    assert current["config"] == {"capacity_warn": None, "capacity_crit": 90}
    shipped_checks, shipped_alerts = canonical_definitions(
        shipped["check_definitions"], shipped["alert_definitions"]
    )
    assert body["shipped"] == {"checkDefinitions": shipped_checks, "alertDefinitions": []}
    assert shipped_checks[0]["config"] == {"capacity_warn": 80, "capacity_crit": 90}


def test_numbers_at_the_float_limit_stay():
    text = '{"in": [1e308, ' + str(10**308) + ', -1.5e-320], "out": [-1e400, -' + _BIG_INT + "]}"

    assert loads_readable(text) == {"in": [1e308, 10**308, -1.5e-320], "out": [None, None]}


def test_stored_rows_stay_unchanged(client_db):
    """Reading does not migrate: the columns keep their text, the scheduler and the template sync
    read them on their own."""
    client, factory = client_db
    _seed(factory)

    for path in ("/status", "/checks", "/checks/chk-1", "/alerts", "/templates"):
        assert client.get(path).status_code == 200

    with factory() as db:
        assert db.get(MonitorCheck, "chk-1").config == '{"reallocated_warn": Infinity}'
        assert "NaN" in db.get(MonitorState, "chk-1").details
        assert "NaN" in db.get(MonitorAlertRule, "rule-1").channel_config
        assert "Infinity" in db.get(MonitorTemplate, "tpl-1").check_definitions
