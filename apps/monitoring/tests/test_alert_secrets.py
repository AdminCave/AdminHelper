# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SMTP secret handling (3.27): the password is masked in API responses, and a
masked/empty password on update keeps the stored secret instead of overwriting it —
so it is never reflected to callers nor wiped by editing an unrelated field."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorAlertRule


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
