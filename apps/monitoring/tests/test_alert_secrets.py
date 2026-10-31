# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SMTP secret handling (3.27): the password is masked in API responses, and a
masked/empty password on update keeps the stored secret instead of overwriting it —
so it is never reflected to callers nor wiped by editing an unrelated field.
Templates carry the same channel_config in their alert definitions and follow the
same rule, matched by def_id: the desktop sends a definition back as it read it.
The stored secret is kept only for the relay it was stored for (smtp_host and
smtp_port): a PUT that changes the relay has to send the password again."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import builtin_templates
from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorAlertRule, MonitorTemplate


def test_to_dict_masks_a_set_smtp_password():
    rule = MonitorAlertRule(
        id="r1",
        name="r",
        channel="email",
        channel_config=json.dumps({"to": "a@x.de", "smtp_password": "secret"}),
    )
    assert rule.to_dict()["channelConfig"]["smtp_password"] == "***"


def test_to_dict_leaves_config_without_password_untouched():
    rule = MonitorAlertRule(
        id="r2",
        name="r",
        channel="email",
        channel_config=json.dumps({"to": "a@x.de"}),
    )
    assert "smtp_password" not in rule.to_dict()["channelConfig"]


@pytest.fixture()
def client_db():
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_internal] = lambda: None
    yield TestClient(app), factory
    app.dependency_overrides.clear()


def _seed_email_rule(factory, password="real-secret"):
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1",
                name="r",
                channel="email",
                channel_config=json.dumps({"to": "a@x.de", "smtp_password": password}),
            )
        )
        db.commit()


def test_get_alerts_masks_the_password(client_db):
    client, factory = client_db
    _seed_email_rule(factory)
    body = client.get("/alerts").json()
    rule = body[0] if isinstance(body, list) else body["items"][0]
    assert rule["channelConfig"]["smtp_password"] == "***"


def test_update_with_masked_password_keeps_stored_secret(client_db):
    client, factory = client_db
    _seed_email_rule(factory, password="real-secret")
    # PUT the masked value back (as the frontend would after loading the masked GET)
    r = client.put(
        "/alerts/r1",
        json={"channel_config": {"to": "b@y.de", "smtp_password": "***"}},
    )
    assert r.status_code == 200, r.text
    with factory() as db:
        stored = json.loads(db.get(MonitorAlertRule, "r1").channel_config)
    assert stored["smtp_password"] == "real-secret"  # unchanged, not overwritten by ***
    assert stored["to"] == "b@y.de"  # the other field DID update


def test_update_with_real_password_overwrites(client_db):
    client, factory = client_db
    _seed_email_rule(factory, password="old")
    r = client.put(
        "/alerts/r1",
        json={"channel_config": {"to": "a@x.de", "smtp_password": "new-secret"}},
    )
    assert r.status_code == 200, r.text
    with factory() as db:
        stored = json.loads(db.get(MonitorAlertRule, "r1").channel_config)
    assert stored["smtp_password"] == "new-secret"


# --- Templates: the alert definitions carry the same channel_config -----------------


def _email_def(def_id="def-mail", smtp_password="tpl-secret") -> dict:
    d = {
        "name": "Mail",
        "channel": "email",
        "channel_config": {
            "to": "ops@relay.example",
            "smtp_host": "relay.example",
            "smtp_password": smtp_password,
        },
    }
    if def_id is not None:
        d["def_id"] = def_id
    return d


def _create_template(client, smtp_password="tpl-secret"):
    r = client.post(
        "/templates",
        json={"name": "T", "alert_definitions": [_email_def(smtp_password=smtp_password)]},
    )
    assert r.status_code == 201, r.text
    return r


def _stored_alert_defs(factory, tid) -> list[dict]:
    with factory() as db:
        return json.loads(db.get(MonitorTemplate, tid).alert_definitions)


def test_template_to_dict_masks_only_a_set_password():
    defs = [
        _email_def(),
        _email_def(def_id="def-empty", smtp_password=""),
        {"def_id": "def-bare", "name": "Bare", "channel": "webhook"},
        "not-a-definition",
    ]
    tpl = MonitorTemplate(id="t1", name="T", alert_definitions=json.dumps(defs))
    shown = tpl.to_dict(builtin_edited=False, builtin_update_available=False)["alertDefinitions"]
    assert shown[0]["channel_config"]["smtp_password"] == "***"
    assert shown[0]["channel_config"]["to"] == "ops@relay.example"
    assert shown[1:] == defs[1:]


def test_template_responses_mask_the_alert_password(client_db):
    client, factory = client_db
    created = _create_template(client)
    tid = created.json()["id"]
    listed = client.get("/templates")
    single = client.get(f"/templates/{tid}")
    assert (listed.status_code, single.status_code) == (200, 200)

    for r in (created, listed, single):
        assert "tpl-secret" not in r.text
    shown = [created.json(), next(t for t in listed.json() if t["id"] == tid), single.json()]
    for t in shown:
        assert t["alertDefinitions"][0]["channel_config"]["smtp_password"] == "***"
    # Only the answer is masked; the template keeps the password.
    assert _stored_alert_defs(factory, tid)[0]["channel_config"]["smtp_password"] == "tpl-secret"


def test_template_put_with_the_mask_keeps_the_stored_password(client_db):
    client, factory = client_db
    tid = _create_template(client).json()["id"]
    defs = client.get(f"/templates/{tid}").json()["alertDefinitions"]
    defs[0]["channel_config"]["to"] = "oncall@relay.example"

    r = client.put(f"/templates/{tid}", json={"alert_definitions": defs})

    assert r.status_code == 200, r.text
    assert "tpl-secret" not in r.text
    stored = _stored_alert_defs(factory, tid)[0]["channel_config"]
    assert stored["smtp_password"] == "tpl-secret"
    assert stored["to"] == "oncall@relay.example"


def test_template_put_with_a_new_password_overwrites(client_db):
    client, factory = client_db
    tid = _create_template(client).json()["id"]

    r = client.put(
        f"/templates/{tid}",
        json={"alert_definitions": [_email_def(smtp_password="new-secret")]},
    )

    assert r.status_code == 200, r.text
    assert _stored_alert_defs(factory, tid)[0]["channel_config"]["smtp_password"] == "new-secret"


@pytest.mark.parametrize("def_id", ["def-new", None])
def test_template_put_with_the_mask_on_a_new_definition_stores_no_password(client_db, def_id):
    # No stored definition with that def_id (or none sent): nothing to keep.
    client, factory = client_db
    tid = _create_template(client).json()["id"]

    r = client.put(
        f"/templates/{tid}",
        json={"alert_definitions": [_email_def(def_id=def_id, smtp_password="***")]},
    )

    assert r.status_code == 200, r.text
    stored = _stored_alert_defs(factory, tid)
    assert len(stored) == 1
    assert stored[0]["def_id"] not in ("def-mail", None)
    assert "smtp_password" not in stored[0]["channel_config"]


def test_template_post_with_an_empty_password_stores_none(client_db):
    client, factory = client_db
    tid = _create_template(client, smtp_password="").json()["id"]
    assert "smtp_password" not in _stored_alert_defs(factory, tid)[0]["channel_config"]


def test_template_post_with_the_mask_as_password_is_refused(client_db):
    # A new template has no stored password the mask could stand for, as POST /alerts.
    client, factory = client_db
    r = client.post(
        "/templates",
        json={"name": "T", "alert_definitions": [_email_def(smtp_password="***")]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "smtp_password must be the password itself, not the mask '***'"
    with factory() as db:
        assert db.query(MonitorTemplate).count() == 0


def test_builtin_update_masks_the_current_alert_password(client_db):
    client, factory = client_db
    shipped = builtin_templates.BUILTIN_TEMPLATES[0]
    with factory() as db:
        db.add(
            MonitorTemplate(
                id="tpl-builtin",
                name="Built-in",
                builtin_slug=shipped["slug"],
                builtin_version=shipped["version"],
                check_definitions="[]",
                alert_definitions=json.dumps([_email_def()]),
            )
        )
        db.commit()

    r = client.get("/templates/tpl-builtin/builtin-update")

    assert r.status_code == 200, r.text
    assert "tpl-secret" not in r.text
    current = r.json()["current"]["alertDefinitions"]
    assert current[0]["channel_config"]["smtp_password"] == "***"


def test_template_put_with_the_mask_keeps_the_password_of_its_rules(client_db):
    # The sync writes the template's channel_config into every rule made from it.
    client, factory = client_db
    tid = _create_template(client).json()["id"]
    r = client.post(
        f"/templates/{tid}/assign",
        json={"server_id": "srv-1", "hostname": "h", "server_name": "n"},
    )
    assert r.status_code == 200, r.text

    r = client.put(
        f"/templates/{tid}", json={"alert_definitions": [_email_def(smtp_password="***")]}
    )

    assert r.status_code == 200, r.text
    with factory() as db:
        rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.template_id == tid).one()
        assert json.loads(rule.channel_config)["smtp_password"] == "tpl-secret"


# --- The mask keeps the password only for the relay it was stored for -------------

_RELAY_CHANGED = "smtp_password must be entered again when smtp_host or smtp_port changes"
_ASSIGN = {"server_id": "srv-1", "hostname": "h", "server_name": "n"}


def _relay_a_config(smtp_password="real-secret") -> dict:
    return {
        "recipients": ["ops@relay-a.example"],
        "smtp_host": "relay-a.example",
        "smtp_port": 587,
        "smtp_password": smtp_password,
    }


def _seed_relay_a_rule(factory):
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1",
                name="r",
                channel="email",
                channel_config=json.dumps(_relay_a_config()),
            )
        )
        db.commit()


def _stored_rule(factory, rule_id="r1") -> tuple[str, dict]:
    with factory() as db:
        rule = db.get(MonitorAlertRule, rule_id)
        return rule.name, json.loads(rule.channel_config)


@pytest.mark.parametrize(
    "relay",
    [
        pytest.param({"smtp_host": "relay-b.example"}, id="host"),
        pytest.param({"smtp_port": 2525}, id="port"),
        pytest.param({"smtp_host": None}, id="host-removed"),
        pytest.param({"smtp_host": "  "}, id="host-blank"),
        pytest.param({"smtp_port": None}, id="port-removed"),
    ],
)
def test_alert_put_with_the_mask_for_another_relay_is_refused(client_db, relay):
    client, factory = client_db
    _seed_relay_a_rule(factory)

    r = client.put(
        "/alerts/r1",
        json={"name": "renamed", "channel_config": {**_relay_a_config("***"), **relay}},
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _RELAY_CHANGED
    # Nothing of the refused PUT is stored, the other fields included.
    assert _stored_rule(factory) == ("r", _relay_a_config())


def test_alert_put_with_the_mask_for_the_same_relay_keeps_the_password(client_db):
    # Host compared after strip() and in lower case, the port as text.
    client, factory = client_db
    _seed_relay_a_rule(factory)
    sent = {**_relay_a_config("***"), "smtp_host": " RELAY-A.example ", "smtp_port": "587"}

    r = client.put("/alerts/r1", json={"channel_config": sent})

    assert r.status_code == 200, r.text
    assert _stored_rule(factory)[1]["smtp_password"] == "real-secret"


def test_alert_put_with_a_new_password_for_another_relay_stores_it(client_db):
    client, factory = client_db
    _seed_relay_a_rule(factory)
    sent = {**_relay_a_config("new-secret"), "smtp_host": "relay-b.example"}

    r = client.put("/alerts/r1", json={"channel_config": sent})

    assert r.status_code == 200, r.text
    stored = _stored_rule(factory)[1]
    assert (stored["smtp_host"], stored["smtp_password"]) == ("relay-b.example", "new-secret")


def test_alert_put_without_relay_and_password_drops_the_stored_password(client_db):
    # The desktop sends only the recipients when it edits an e-mail rule: the save
    # goes through, and the password stays off the relay from SMTP_HOST.
    client, factory = client_db
    _seed_relay_a_rule(factory)
    sent = {"recipients": ["oncall@relay-a.example"]}

    r = client.put("/alerts/r1", json={"channel_config": sent})

    assert r.status_code == 200, r.text
    assert _stored_rule(factory)[1] == sent


def _relay_a_template(client) -> str:
    """A template with one e-mail definition for relay-a.example, assigned to srv-1."""
    definition = _email_def()
    definition["channel_config"]["smtp_host"] = "relay-a.example"
    r = client.post("/templates", json={"name": "T", "alert_definitions": [definition]})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(f"/templates/{tid}/assign", json=_ASSIGN)
    assert r.status_code == 200, r.text
    return tid


def _relay_b_def(**channel_config) -> dict:
    definition = _email_def()
    definition["channel_config"].pop("smtp_password")
    definition["channel_config"].update(smtp_host="relay-b.example", **channel_config)
    return definition


def _template_rule_config(factory, tid) -> dict:
    with factory() as db:
        rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.template_id == tid).one()
        return json.loads(rule.channel_config)


def test_template_put_with_the_mask_for_another_relay_is_refused(client_db):
    client, factory = client_db
    tid = _relay_a_template(client)

    r = client.put(
        f"/templates/{tid}",
        json={"name": "renamed", "alert_definitions": [_relay_b_def(smtp_password="***")]},
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == _RELAY_CHANGED
    with factory() as db:
        assert db.get(MonitorTemplate, tid).name == "T"
    stored = _stored_alert_defs(factory, tid)[0]["channel_config"]
    assert (stored["smtp_host"], stored["smtp_password"]) == ("relay-a.example", "tpl-secret")
    rule = _template_rule_config(factory, tid)
    assert (rule["smtp_host"], rule["smtp_password"]) == ("relay-a.example", "tpl-secret")


def test_template_put_for_another_relay_without_password_drops_it(client_db):
    client, factory = client_db
    tid = _relay_a_template(client)

    r = client.put(f"/templates/{tid}", json={"alert_definitions": [_relay_b_def()]})

    assert r.status_code == 200, r.text
    assert "tpl-secret" not in r.text
    stored = _stored_alert_defs(factory, tid)[0]["channel_config"]
    assert stored["smtp_host"] == "relay-b.example"
    assert "smtp_password" not in stored
    # The sync hands the definition on to the rule made from it.
    rule = _template_rule_config(factory, tid)
    assert rule["smtp_host"] == "relay-b.example"
    assert "smtp_password" not in rule


def test_alert_post_with_the_mask_as_password_is_refused(client_db):
    # A new rule has no stored password the mask could stand for: storing "***" would
    # send it to the relay as the password.
    client, factory = client_db

    r = client.post(
        "/alerts",
        json={"name": "r", "channel": "email", "channel_config": _relay_a_config("***")},
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "smtp_password must be the password itself, not the mask '***'"
    with factory() as db:
        assert db.query(MonitorAlertRule).count() == 0
