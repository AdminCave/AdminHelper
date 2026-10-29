# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A check name carries no control character below U+0020 and no DEL: such a name
is a 422 at its own location, when a check is created, when an update sends the
name, and in the check definitions of a template. Every other character passes,
C1 and U+2028 included; the alert subject turns those into spaces itself."""

import pytest

from app.models import MonitorCheck, MonitorTemplate

_MSG = "Value error, must not contain control characters"
_CONTROL_NAMES = ["a\nb", "a\rb", "a\tb", "a\x7fb"]
_PLAIN_NAMES = ["Web 1 – Grüße ✓", "a b", "a\x85b"]


def _check(name: str) -> dict:
    return {"name": name, "check_type": "ping", "config": {"target": "192.0.2.1"}, "enabled": False}


def _template(check_name: str) -> dict:
    return {
        "name": "t1",
        "check_definitions": [
            {"name": check_name, "check_type": "ping", "config": {"target": "{{hostname}}"}}
        ],
    }


def _store_check(factory, name: str) -> None:
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name=name,
                check_type="ping",
                config='{"target": "192.0.2.1"}',
                enabled=False,
            )
        )
        db.commit()


def _the_one_error(r) -> dict:
    assert r.status_code == 422, r.text
    errors = r.json()["detail"]
    assert len(errors) == 1, errors
    return errors[0]


@pytest.mark.parametrize("name", _CONTROL_NAMES)
def test_creating_a_check_with_a_control_character_in_its_name_is_422(name, client_db):
    client, factory = client_db
    error = _the_one_error(client.post("/checks", json=_check(name)))
    assert error["loc"] == ["body", "name"]
    assert error["msg"] == _MSG
    with factory() as db:
        assert db.query(MonitorCheck).count() == 0


@pytest.mark.parametrize("name", _CONTROL_NAMES)
def test_renaming_a_check_to_a_name_with_a_control_character_is_422(name, client_db):
    client, factory = client_db
    _store_check(factory, "web")
    error = _the_one_error(client.put("/checks/c1", json={"name": name}))
    assert error["loc"] == ["body", "name"]
    assert error["msg"] == _MSG
    with factory() as db:
        assert db.get(MonitorCheck, "c1").name == "web"


def test_an_update_without_the_name_passes_whatever_name_is_stored(client_db):
    # A name stored before the rule: only a name the request sends is checked.
    client, factory = client_db
    _store_check(factory, "old\nname")
    r = client.put("/checks/c1", json={"interval": "15m"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "old\nname"
    assert r.json()["interval"] == "15m"


def test_a_template_check_definition_with_a_control_character_in_its_name_is_422(client_db):
    client, factory = client_db
    error = _the_one_error(client.post("/templates", json=_template("x\ny")))
    assert error["loc"] == ["body", "check_definitions", 0, "name"]
    assert error["msg"] == _MSG
    with factory() as db:
        assert db.query(MonitorTemplate).count() == 0


@pytest.mark.parametrize("name", _PLAIN_NAMES)
def test_a_name_without_c0_or_del_is_accepted(name, client_db):
    client, _ = client_db
    r = client.post("/checks", json=_check(name))
    assert r.status_code == 201, r.text
    assert r.json()["name"] == name
    r = client.post("/templates", json=_template(name))
    assert r.status_code == 201, r.text
