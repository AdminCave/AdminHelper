# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The channel settings of a person (R-1080): revision f3a5c7e9b1d2 turns the channel
ticks of the rules into the matrix severity x channel and back, the matrix routes the
outbox, and the prefs API reads and writes it.

The migration tests follow test_notification_category_migration.py: a throwaway
database on the session's Postgres, migrated up to the revision before, seeded, then
upgraded."""

import json
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.core.config as app_config
from app.modules.notifications.models import NotificationOutbox, NotificationSettings
from app.modules.notifications.service import channels_for, ingest_event, notify_users
from tests.test_notifications import _event, _login, _server, _sub, _user

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "f3a5c7e9b1d2"
PREVIOUS = "c8e2f4a6b0d1"
ROWS = ("critical", "warning", "info", "ok")
PATH = "/api/users/me/notification-prefs"

# --- migration ---------------------------------------------------------------------

# user id: rules (min_severity, email, telegram, enabled) -> matrix after the upgrade
PEOPLE = {
    # One rule from warning with e-mail: warning, critical and the all-clear.
    1: (
        [("warning", True, False, True)],
        {
            "critical": ["desktop", "email"],
            "warning": ["desktop", "email"],
            "info": ["desktop"],
            "ok": ["desktop", "email"],
        },
    ),
    # Telegram from critical on one rule, e-mail from info on another; a switched-off
    # rule with both ticks adds nothing; an unknown floor counts as info.
    2: (
        [
            ("critical", False, True, True),
            ("bogus", True, False, True),
            ("info", True, True, False),
        ],
        {
            "critical": ["desktop", "email", "telegram"],
            "warning": ["desktop", "email"],
            "info": ["desktop", "email"],
            "ok": ["desktop", "email", "telegram"],
        },
    ),
    # Rules without ticks: the desktop alone, as toasts came for everything.
    3: ([("warning", False, False, True)], {row: ["desktop"] for row in ROWS}),
}


@pytest.fixture()
def before_matrix(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_matrix_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    url = admin_url.set(database=dbname).render_as_string(hide_password=False)
    # env.py reads app.core.config.DATABASE_URL at execution time — patch the attribute.
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    engine = create_engine(url)
    try:
        command.upgrade(cfg, PREVIOUS)
        _seed(engine)
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _seed(engine) -> None:
    with engine.begin() as conn:
        # User 4 has no rule and gets no settings row.
        for uid in (*PEOPLE, 4):
            conn.execute(
                text(
                    "INSERT INTO users (id, username, hashed_password, is_admin)"
                    " VALUES (:id, :name, 'x', true)"
                ),
                {"id": uid, "name": f"user{uid}"},
            )
        for uid, (rules, _) in PEOPLE.items():
            for min_severity, email, telegram, enabled in rules:
                conn.execute(
                    text(
                        "INSERT INTO notification_subscription (user_id, scope_type,"
                        " min_severity, channel_email, channel_telegram, enabled)"
                        " VALUES (:u, 'all', :m, :e, :t, :on)"
                    ),
                    {"u": uid, "m": min_severity, "e": email, "t": telegram, "on": enabled},
                )


def _settings(engine) -> dict[int, tuple[dict, list, list]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT user_id, matrix, disabled_channels, muted_categories"
                " FROM notification_settings ORDER BY user_id"
            )
        ).all()
    return {u: (json.loads(m), json.loads(d), json.loads(c)) for u, m, d, c in rows}


def _ticks(engine) -> dict[int, set[tuple[bool, bool]]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT user_id, channel_email, channel_telegram FROM notification_subscription")
        ).all()
    ticks: dict[int, set[tuple[bool, bool]]] = {}
    for uid, email, telegram in rows:
        ticks.setdefault(uid, set()).add((email, telegram))
    return ticks


def _columns(engine) -> set[str]:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'notification_subscription'"
                )
            )
        }


def test_upgrade_turns_the_ticks_into_the_matrix(before_matrix):
    cfg, engine = before_matrix

    command.upgrade(cfg, REVISION)

    assert _settings(engine) == {uid: (matrix, [], []) for uid, (_, matrix) in PEOPLE.items()}
    assert not {"channel_email", "channel_telegram"} & _columns(engine)


def test_downgrade_ticks_every_rule_of_a_used_channel(before_matrix):
    cfg, engine = before_matrix
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        # User 3 picks telegram after the upgrade, then switches it off: no tick.
        matrix = {row: ["desktop", "telegram"] for row in ROWS}
        conn.execute(
            text(
                "UPDATE notification_settings SET matrix = :m, disabled_channels = :d"
                " WHERE user_id = 3"
            ),
            {"m": json.dumps(matrix), "d": '["telegram"]'},
        )

    command.downgrade(cfg, PREVIOUS)

    # Counter-check of the upgrade: user 1 gets back exactly the tick it had; user 2
    # had them on different rules, the downgrade puts both on every rule (the matrix is
    # finer than the ticks, documented in the revision).
    assert _ticks(engine) == {1: {(True, False)}, 2: {(True, True)}, 3: {(False, False)}}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('notification_settings')")).scalar() is None


# --- routing -------------------------------------------------------------------------


def _store(db, user, matrix=None, disabled=(), muted=()):
    db.add(
        NotificationSettings(
            user_id=user.id,
            matrix=json.dumps(matrix or {row: ["desktop"] for row in ROWS}),
            disabled_channels=json.dumps(list(disabled)),
            muted_categories=json.dumps(list(muted)),
        )
    )
    db.commit()


def _queued(db, user) -> list[str]:
    rows = db.query(NotificationOutbox).filter_by(user_id=user.id).all()
    return sorted(r.channel for r in rows)


def _person(db):
    _server(db, "srv-1")
    admin = _user(db, "boss", is_admin=True, email="a@b.de", telegram_chat_id="4711")
    _sub(db, admin, scope_type="all", min_severity="info")
    return admin


MATRIX = {
    "critical": ["desktop", "email", "telegram"],
    "warning": ["telegram"],
    "info": [],
    "ok": ["email"],
}


class TestChannelsFor:
    def test_without_settings_the_desktop_alone(self):
        for level in ROWS:
            assert channels_for(None, level, "monitoring") == ["desktop"]

    def test_an_unknown_level_takes_the_critical_row(self):
        settings = NotificationSettings(
            matrix=json.dumps(MATRIX), disabled_channels="[]", muted_categories="[]"
        )
        assert channels_for(settings, "bogus", "monitoring") == MATRIX["critical"]

    def test_switched_off_and_muted(self):
        settings = NotificationSettings(
            matrix=json.dumps(MATRIX),
            disabled_channels='["email"]',
            muted_categories='["security"]',
        )
        assert channels_for(settings, "critical", "monitoring") == ["desktop", "telegram"]
        assert channels_for(settings, "critical", "security") == []


class TestRouting:
    @pytest.fixture(autouse=True)
    def _telegram_bot(self, monkeypatch):
        # Telegram entries are queued only with a bot token (R-1080).
        monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "test-token")

    @pytest.mark.parametrize(
        ("severity", "new_status", "expected"),
        [
            ("critical", None, ["email", "telegram"]),
            ("warning", None, ["telegram"]),
            ("info", None, []),
            ("critical", "ok", ["email"]),
        ],
    )
    def test_each_row_of_the_matrix(self, db_session, severity, new_status, expected):
        admin = _person(db_session)
        _store(db_session, admin, MATRIX)
        event = _event(severity=severity)
        event.new_status = new_status
        assert ingest_event(db_session, event) == 1
        assert _queued(db_session, admin) == expected

    def test_without_settings_no_outbox_entry(self, db_session):
        admin = _person(db_session)
        assert ingest_event(db_session, _event()) == 1
        assert _queued(db_session, admin) == []

    def test_a_muted_category_reaches_the_bell_only(self, db_session):
        admin = _person(db_session)
        _store(db_session, admin, MATRIX, muted=["monitoring"])
        assert ingest_event(db_session, _event(category="monitoring")) == 1
        assert _queued(db_session, admin) == []
        assert ingest_event(db_session, _event(category="security", source_id=None)) == 1
        assert _queued(db_session, admin) == ["email", "telegram"]

    def test_a_switched_off_channel_gets_no_entry(self, db_session):
        admin = _person(db_session)
        _store(db_session, admin, MATRIX, disabled=["telegram"])
        assert ingest_event(db_session, _event()) == 1
        assert _queued(db_session, admin) == ["email"]

    def test_no_address_no_entry(self, db_session):
        _server(db_session, "srv-1")
        admin = _user(db_session, "boss", is_admin=True, email="a@b.de")
        _sub(db_session, admin, scope_type="all")
        _store(db_session, admin, MATRIX)
        assert ingest_event(db_session, _event()) == 1
        assert _queued(db_session, admin) == ["email"]

    def test_notify_users_reaches_the_bell_only(self, db_session):
        admin = _person(db_session)
        _store(db_session, admin, MATRIX)
        notify_users(db_session, [admin], _event())
        assert _queued(db_session, admin) == []


# --- prefs API -----------------------------------------------------------------------


class TestPrefsApi:
    def test_get_defaults(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr(app_config, "SMTP_HOST", "")
        monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
        _user(db_session, "alice")
        body = test_client.get(PATH, headers=_login(test_client, "alice")).json()
        assert body["ntfyUrl"] is None and body["webhookUrl"] is None
        assert body["matrix"] == {row: ["desktop"] for row in ROWS}
        assert (body["disabledChannels"], body["mutedCategories"]) == ([], [])
        # R-1081: everything off, the times prefilled, critical let through.
        assert body["timezone"] == "UTC"
        assert body["quiet"] == {
            "enabled": False,
            "start": "22:00",
            "end": "07:00",
            "critical": True,
        }
        assert body["escalation"] == {"enabled": False, "minutes": 10, "channel": None}
        assert (body["digest"], body["soundCritical"]) == ("off", False)
        assert body["available"] == {
            "desktop": True,
            "email": False,
            "ntfy": True,
            "telegram": False,
            "webhook": True,
        }

    def test_email_available_with_smtp_host(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr(app_config, "SMTP_HOST", "smtp.example.org")
        _user(db_session, "alice")
        body = test_client.get(PATH, headers=_login(test_client, "alice")).json()
        assert body["available"]["email"] is True

    def test_telegram_available_with_bot_token(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "123456:token")
        _user(db_session, "alice")
        body = test_client.get(PATH, headers=_login(test_client, "alice")).json()
        assert body["available"]["telegram"] is True

    def test_put_then_get_and_normalised(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        payload = {
            "subscriptions": [{"scope_type": "all"}],
            "ntfy_url": "https://ntfy.example.org/topic?auth=abc",
            "webhook_url": "http://192.0.2.10:8080/hook",
            "matrix": {"critical": ["webhook", "email", "email"], "ok": ["ntfy"]},
            "disabled_channels": ["telegram", "email", "telegram"],
            "muted_categories": ["security", "security", "agent"],
        }
        res = test_client.put(PATH, headers=headers, json=payload)
        assert res.status_code == 200, res.text
        body = test_client.get(PATH, headers=headers).json()
        assert body["ntfyUrl"] == "https://ntfy.example.org/topic?auth=abc"
        assert body["webhookUrl"] == "http://192.0.2.10:8080/hook"
        # In the order of the channels, without repeats; a row not sent is empty.
        assert body["matrix"] == {
            "critical": ["email", "webhook"],
            "warning": [],
            "info": [],
            "ok": ["ntfy"],
        }
        assert body["disabledChannels"] == ["email", "telegram"]
        assert body["mutedCategories"] == ["security", "agent"]

    def test_put_without_the_new_fields_keeps_them(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        first = {
            "subscriptions": [],
            "ntfy_url": "https://ntfy.example.org/t",
            "matrix": {"critical": ["ntfy"]},
            "muted_categories": ["agent"],
        }
        assert test_client.put(PATH, headers=headers, json=first).status_code == 200
        second = {"email": "alice@example.com", "subscriptions": [{"scope_type": "all"}]}
        assert test_client.put(PATH, headers=headers, json=second).status_code == 200
        body = test_client.get(PATH, headers=headers).json()
        assert body["ntfyUrl"] == "https://ntfy.example.org/t"
        assert body["matrix"]["critical"] == ["ntfy"]
        assert body["mutedCategories"] == ["agent"]
        assert len(body["subscriptions"]) == 1

    def test_a_url_sent_as_null_is_cleared(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        first = {"subscriptions": [], "webhook_url": "https://hooks.example.org/x"}
        assert test_client.put(PATH, headers=headers, json=first).status_code == 200
        got = test_client.get(PATH, headers=headers).json()
        assert got["webhookUrl"] == "https://hooks.example.org/x"
        cleared = {"subscriptions": [], "webhook_url": None}
        assert test_client.put(PATH, headers=headers, json=cleared).status_code == 200
        assert test_client.get(PATH, headers=headers).json()["webhookUrl"] is None

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://ntfy.example.org/t",
            "https://",
            "ntfy.example.org/t",
            "https://user:pw@ntfy.example.org/t",
            "https://ntfy.example.org/" + "a" * 2048,
        ],
    )
    def test_a_bad_url_is_422(self, test_client, db_session, url):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        res = test_client.put(PATH, headers=headers, json={"subscriptions": [], "ntfy_url": url})
        assert res.status_code == 422, url

    @pytest.mark.parametrize(
        "extra",
        [
            {"matrix": {"critical": ["pager"]}},
            {"matrix": {"urgent": ["email"]}},
            {"disabled_channels": ["pager"]},
            {"muted_categories": [f"c{i}" for i in range(33)]},
            {"muted_categories": [""]},
            {"muted_categories": ["x" * 65]},
        ],
    )
    def test_bad_settings_are_422(self, test_client, db_session, extra):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        res = test_client.put(PATH, headers=headers, json={"subscriptions": [], **extra})
        assert res.status_code == 422, extra


CLOCK = {
    "timezone": "Europe/Berlin",
    "quiet": {"enabled": True, "start": "23:30", "end": "06:15", "critical": False},
    "escalation": {"enabled": True, "minutes": 5, "channel": "ntfy"},
    "digest": "weekly",
    "sound_critical": True,
}


class TestClockPrefsApi:
    """Quiet hours, escalation, digest and sound (R-1081) through the prefs API."""

    def test_put_then_get(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        res = test_client.put(PATH, headers=headers, json={"subscriptions": [], **CLOCK})
        assert res.status_code == 200, res.text
        body = test_client.get(PATH, headers=headers).json()
        assert body["timezone"] == "Europe/Berlin"
        assert body["quiet"] == CLOCK["quiet"]
        assert body["escalation"] == CLOCK["escalation"]
        assert (body["digest"], body["soundCritical"]) == ("weekly", True)

    def test_a_put_without_them_keeps_them(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        assert (
            test_client.put(PATH, headers=headers, json={"subscriptions": [], **CLOCK}).status_code
            == 200
        )
        rules_only = {"subscriptions": [{"scope_type": "all"}], "matrix": {"critical": ["email"]}}
        assert test_client.put(PATH, headers=headers, json=rules_only).status_code == 200
        body = test_client.get(PATH, headers=headers).json()
        assert body["timezone"] == "Europe/Berlin"
        assert body["quiet"] == CLOCK["quiet"]
        assert body["escalation"] == CLOCK["escalation"]
        assert (body["digest"], body["soundCritical"]) == ("weekly", True)

    def test_an_escalation_switched_off_may_drop_its_channel(self, test_client, db_session):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        off = {"enabled": False, "minutes": 30, "channel": None}
        res = test_client.put(PATH, headers=headers, json={"subscriptions": [], "escalation": off})
        assert res.status_code == 200, res.text
        assert res.json()["escalation"] == off

    def test_a_channel_without_target_is_stored(self, test_client, db_session):
        # The job skips the person; the desktop shows the hint (spec).
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        on = {"enabled": True, "minutes": 10, "channel": "webhook"}
        res = test_client.put(PATH, headers=headers, json={"subscriptions": [], "escalation": on})
        assert res.status_code == 200, res.text
        assert res.json()["webhookUrl"] is None
        assert res.json()["escalation"] == on

    @pytest.mark.parametrize(
        "extra",
        [
            {"timezone": "Mars/Olympus"},
            {"timezone": "../../etc/passwd"},
            {"timezone": "/usr/share/zoneinfo/UTC"},
            {"timezone": ""},
            {"timezone": "E" * 65},
            {"quiet": {"enabled": True, "start": "24:00", "end": "07:00", "critical": True}},
            {"quiet": {"enabled": True, "start": "7:00", "end": "07:00", "critical": True}},
            {"quiet": {"enabled": True, "start": "22:60", "end": "07:00", "critical": True}},
            # Arabic-Indic digits: a Unicode \d would take them.
            {
                "quiet": {
                    "enabled": True,
                    "start": "\u0662\u0662:00",
                    "end": "07:00",
                    "critical": True,
                }
            },
            {"quiet": {"enabled": True, "start": "22:00", "critical": True}},
            {"escalation": {"enabled": True, "minutes": 15, "channel": "email"}},
            {"escalation": {"enabled": True, "minutes": 10, "channel": "desktop"}},
            {"escalation": {"enabled": True, "minutes": 10, "channel": None}},
            {"digest": "hourly"},
        ],
    )
    def test_bad_values_are_422(self, test_client, db_session, extra):
        _user(db_session, "alice")
        headers = _login(test_client, "alice")
        res = test_client.put(PATH, headers=headers, json={"subscriptions": [], **extra})
        assert res.status_code == 422, extra
