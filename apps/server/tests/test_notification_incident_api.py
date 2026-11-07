# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The bell's incident API (R-1079): what a reader sees of an incident and may do.

Pinned here: least privilege per route (no row or no sight now is 404 alike, an
incident without a server is the admins', a partly seen bundle shows only the
reader's servers and history, the team actions need sight of every server), the
transitions and their conflicts, ack in bulk, personal mutes and their bounds,
hide and unread on own rows only, the badge, the feed order and fields, and whom
each action nudges over SSE."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.auth import create_access_token
from app.modules.notifications import stream_hub
from app.modules.notifications.incidents import ingest
from app.modules.notifications.models import (
    Notification,
    NotificationIncident,
    NotificationIncidentEvent,
    NotificationSettings,
)
from app.modules.notifications.schemas import IncomingEvent
from tests.token_claims import claims_for

from .test_notification_incidents import _admin, _at, _check, _heartbeat, _heartbeats
from .test_notifications import _channels, _server, _sub, _user

API = "/api/notifications"


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(claims_for(user.username))}"}


def _soon(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _incidents(db):
    return db.query(NotificationIncident).order_by(NotificationIncident.id).all()


def _row(db, user, incident):
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.incident_id == incident.id)
        .one()
    )


def _feed(client, user) -> list[dict]:
    res = client.get(API, headers=_auth(user))
    assert res.status_code == 200, res.text
    return res.json()


def _count(client, user) -> int:
    res = client.get(f"{API}/unread-count", headers=_auth(user))
    assert res.status_code == 200, res.text
    return res.json()["count"]


@pytest.fixture()
def servers(db_session):
    return [_server(db_session, "srv-1", name="web01"), _server(db_session, "srv-2", name="db01")]


@pytest.fixture()
def published(monkeypatch):
    calls: list = []
    monkeypatch.setattr(stream_hub, "publish", lambda uids, mid: calls.append(sorted(uids)))
    return calls


@pytest.fixture()
def reader(db_session, servers):
    """A non-admin who sees web01 only."""
    user = _user(db_session, "reader", servers=[servers[0]])
    _sub(db_session, user)
    return user


# --- the feed and the badge -------------------------------------------------------


class TestFeed:
    def test_rows_carry_their_incident_and_sort_by_the_last_ping(
        self, test_client, db_session, servers
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("warning", severity="warning"), now=_at(0))
        ingest(db_session, _check("critical", key="check:2", server="srv-2"), now=_at(1))
        ingest(db_session, _check("critical"), now=_at(2))  # an escalation pings at once

        first, second = _feed(test_client, admin)
        one, two = _incidents(db_session)
        assert (first["incidentId"], first["state"], first["count"]) == (one.id, "open", 2)
        assert first["notifiedAt"] == "2026-11-05T08:02:00Z"
        assert (second["incidentId"], second["notifiedAt"]) == (two.id, "2026-11-05T08:01:00Z")
        assert (first["muted"], first["mutedUntil"], first["muteSource"]) == (False, None, None)
        assert first["ackedBy"] is None and first["resolvedBy"] is None

    def test_a_row_without_an_incident_has_no_incident_fields(self, test_client, db_session):
        admin = _admin(db_session)
        db_session.add(
            Notification(
                user_id=admin.id, severity="info", category="lifecycle", event_type="x", title="t"
            )
        )
        db_session.commit()
        (row,) = _feed(test_client, admin)
        assert (row["incidentId"], row["state"], row["count"], row["muted"]) == (
            None,
            None,
            None,
            False,
        )

    def test_a_revoked_server_takes_the_incident_off_the_row(
        self, test_client, db_session, servers, reader
    ):
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        assert _feed(test_client, reader)[0]["incidentId"] == incident.id

        reader.servers = []
        db_session.commit()

        (row,) = _feed(test_client, reader)
        assert (row["incidentId"], row["state"], row["count"]) == (None, None, None)
        assert row["title"] == "CPU critical on web01", "the row itself stays the reader's"
        res = test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(reader))
        assert res.status_code == 404

    def test_the_badge_leaves_out_hidden_and_muted_rows(
        self, test_client, db_session, servers, published
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("critical", key="check:2", server="srv-2"), now=_at(1))
        ingest(db_session, _check("critical", key="check:3", server="srv-2"), now=_at(2))
        one, two, three = _incidents(db_session)
        h = _auth(admin)
        assert _count(test_client, admin) == 3

        hide = test_client.post(
            f"{API}/hide", headers=h, json={"ids": [_row(db_session, admin, one).id]}
        )
        assert hide.json() == {"updated": 1}
        assert [r["incidentId"] for r in _feed(test_client, admin)] == [three.id, two.id]
        assert _count(test_client, admin) == 2

        mute = test_client.put(
            f"{API}/incidents/{two.id}/mute", headers=h, json={"until": _soon(hours=1)}
        )
        assert mute.status_code == 200, mute.text
        assert _count(test_client, admin) == 1

        server = test_client.put(
            f"{API}/server-mutes/srv-2", headers=h, json={"until": _soon(hours=1)}
        )
        assert server.status_code == 200, server.text
        assert _count(test_client, admin) == 0

    def test_the_next_ping_shows_a_hidden_row_again(self, test_client, db_session, servers):
        admin = _admin(db_session)
        ingest(db_session, _check("warning", severity="warning"), now=_at(0))
        (incident,) = _incidents(db_session)
        row = _row(db_session, admin, incident)
        test_client.post(f"{API}/hide", headers=_auth(admin), json={"ids": [row.id]})
        assert _feed(test_client, admin) == []

        ingest(db_session, _check("critical"), now=_at(1))
        assert [r["incidentId"] for r in _feed(test_client, admin)] == [incident.id]


# --- the detail and least privilege ----------------------------------------------


class TestDetail:
    def test_the_detail_of_an_incident(self, test_client, db_session, servers):
        admin = _admin(db_session)
        rules = [{"name": "Ops mail", "channel": "email", "ok": True}]
        ingest(db_session, _check("critical", rules=rules), now=_at(0))
        ingest(db_session, _check("ok"), now=_at(3))
        (incident,) = _incidents(db_session)

        res = test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(admin))
        assert res.status_code == 200, res.text
        body = res.json()
        assert (body["state"], body["count"], body["bundle"], body["canAct"]) == (
            "resolved",
            1,
            False,
            True,
        )
        assert body["servers"] == [{"id": "srv-1", "name": "web01", "recoveredAt": None}]
        assert body["rules"] == rules
        assert body["channels"] == ["bell", "email"]
        assert [(e["kind"], e["serverId"]) for e in body["history"]] == [
            ("triggered", None),
            ("notified", None),
            ("resolved", None),
            ("notified", None),
        ]
        assert (body["firstAt"], body["lastAt"]) == ("2026-11-05T08:00:00Z", "2026-11-05T08:03:00Z")
        assert body["row"]["incidentId"] == incident.id

    def test_the_detail_names_every_channel_the_ping_went_to(
        self, test_client, db_session, servers
    ):
        admin = _admin(db_session)
        _channels(db_session, admin, "ntfy", "webhook")
        settings = db_session.get(NotificationSettings, admin.id)
        settings.ntfy_url = "https://ntfy.example/alerts"
        settings.webhook_url = "https://hooks.example/in"
        db_session.commit()
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)

        res = test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(admin))
        assert res.status_code == 200, res.text
        assert res.json()["channels"] == ["bell", "email", "ntfy", "webhook"]

    def test_a_reader_sees_only_their_servers_of_a_bundle(
        self, test_client, db_session, servers, reader
    ):
        ingest(db_session, _heartbeats(["srv-1", "srv-2"]), now=_at(0))
        ingest(db_session, _heartbeat("srv-2", "ok"), now=_at(1))
        (incident,) = _incidents(db_session)

        body = test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(reader)).json()
        assert body["servers"] == [{"id": "srv-1", "name": "web01", "recoveredAt": None}]
        assert (body["title"], body["body"]) == (
            "Agents not reporting (1)",
            "Heartbeat lost\n- web01",
        )
        assert all(e["serverId"] in (None, "srv-1") for e in body["history"])
        assert "db01" not in str(body)
        assert body["canAct"] is False
        assert body["count"] == incident.event_count, "the count is the team's"

    def test_without_a_row_of_ones_own_it_is_404(self, test_client, db_session, servers):
        _admin(db_session)
        other = _user(db_session, "other", servers=servers)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        h = _auth(other)

        assert test_client.get(f"{API}/incidents/{incident.id}", headers=h).status_code == 404
        assert test_client.get(f"{API}/incidents/999999", headers=h).status_code == 404
        for verb, path, body in (
            ("post", "resolve", None),
            ("post", "reopen", None),
            ("post", "notes", {"text": "x"}),
            ("put", "mute", {"until": _soon(hours=1)}),
            ("delete", "mute", None),
        ):
            res = test_client.request(
                verb.upper(), f"{API}/incidents/{incident.id}/{path}", headers=h, json=body
            )
            assert res.status_code == 404, (path, res.text)

    def test_an_incident_without_a_server_is_the_admins(self, test_client, db_session, servers):
        admin = _admin(db_session)
        notice = IncomingEvent(
            event_type="frps.down",
            severity="critical",
            category="frp",
            title="frps down",
            source_type="frps",
            incident_key="frps:main",
        )
        ingest(db_session, notice, now=_at(0))
        (incident,) = _incidents(db_session)
        assert (
            test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(admin)).status_code
            == 200
        )

        stray = _user(db_session, "stray", servers=servers)
        db_session.add(
            Notification(
                user_id=stray.id,
                severity="critical",
                category="frp",
                event_type="frps.down",
                title="frps down",
                source_type="frps",
                incident_id=incident.id,
            )
        )
        db_session.commit()
        assert (
            test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(stray)).status_code
            == 404
        )
        assert _feed(test_client, stray)[0]["incidentId"] is None

    def test_the_history_names_the_actors(self, test_client, db_session, servers):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        h = _auth(admin)
        test_client.post(f"{API}/incidents/ack", headers=h, json={"ids": [incident.id]})
        body = test_client.post(
            f"{API}/incidents/{incident.id}/notes", headers=h, json={"text": "on it"}
        ).json()
        assert [(e["kind"], e["actor"]) for e in body["history"]] == [
            ("triggered", None),
            ("notified", None),
            ("acked", "boss"),
            ("note", "boss"),
        ]
        assert body["history"][-1]["text"] == "on it"
        assert (body["ackedBy"], body["row"]["ackedBy"]) == ("boss", "boss")


# --- the team actions -------------------------------------------------------------


class TestTeamActions:
    def test_ack_acks_the_open_ones_and_skips_the_rest(
        self, test_client, db_session, servers, published
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("critical", key="check:2"), now=_at(1))
        ingest(db_session, _check("ok", key="check:2"), now=_at(2))
        open_, resolved = _incidents(db_session)
        published.clear()

        res = test_client.post(
            f"{API}/incidents/ack",
            headers=_auth(admin),
            json={"ids": [resolved.id, 999999, open_.id, open_.id]},
        )
        assert res.status_code == 200, res.text
        assert res.json() == {"updated": 1, "skipped": [resolved.id, 999999]}
        db_session.refresh(open_)
        assert (open_.state, open_.acked_by) == ("acked", admin.id)
        assert published == [[admin.id]]

        again = test_client.post(
            f"{API}/incidents/ack", headers=_auth(admin), json={"ids": [open_.id]}
        )
        assert again.json() == {"updated": 0, "skipped": [open_.id]}
        assert published == [[admin.id]], "nothing changed, nobody is nudged"

    def test_resolve_and_reopen_and_their_conflicts(self, test_client, db_session, servers):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        h = _auth(admin)
        test_client.post(f"{API}/incidents/ack", headers=h, json={"ids": [incident.id]})
        url = f"{API}/incidents/{incident.id}"

        resolved = test_client.post(f"{url}/resolve", headers=h)
        assert resolved.status_code == 200, resolved.text
        body = resolved.json()
        assert (body["state"], body["resolvedBy"], body["ackedBy"]) == ("resolved", "boss", "boss")
        assert test_client.post(f"{url}/resolve", headers=h).status_code == 409

        reopened = test_client.post(f"{url}/reopen", headers=h).json()
        assert (reopened["state"], reopened["resolvedBy"], reopened["ackedBy"]) == (
            "open",
            None,
            None,
        )
        assert test_client.post(f"{url}/reopen", headers=h).status_code == 409
        assert [e["kind"] for e in reopened["history"]][-3:] == ["acked", "resolved", "reopened"]

    def test_a_reader_of_part_of_a_bundle_may_not_act(
        self, test_client, db_session, servers, reader
    ):
        _admin(db_session)
        ingest(db_session, _heartbeats(["srv-1", "srv-2"]), now=_at(0))
        (incident,) = _incidents(db_session)
        h = _auth(reader)
        url = f"{API}/incidents/{incident.id}"

        for path, body in (("resolve", None), ("reopen", None), ("notes", {"text": "x"})):
            assert test_client.post(f"{url}/{path}", headers=h, json=body).status_code == 403, path
        ack = test_client.post(f"{API}/incidents/ack", headers=h, json={"ids": [incident.id]})
        assert ack.json() == {"updated": 0, "skipped": [incident.id]}
        db_session.refresh(incident)
        assert incident.state == "open"

        mute = test_client.put(f"{url}/mute", headers=h, json={"until": _soon(hours=1)})
        assert mute.status_code == 200, "a mute is the reader's own"

    def test_a_note_needs_text_and_goes_in_any_state(self, test_client, db_session, servers):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _check("ok"), now=_at(1))
        (incident,) = _incidents(db_session)
        url = f"{API}/incidents/{incident.id}/notes"
        h = _auth(admin)

        for text in ("", "   ", "x" * 2001):
            assert test_client.post(url, headers=h, json={"text": text}).status_code == 422
        res = test_client.post(url, headers=h, json={"text": "rebooted"})
        assert res.status_code == 200, res.text
        assert res.json()["state"] == "resolved"

    def test_a_team_action_nudges_every_holder(
        self, test_client, db_session, servers, reader, published
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        published.clear()

        test_client.post(f"{API}/incidents/{incident.id}/resolve", headers=_auth(reader))
        assert published == [sorted([admin.id, reader.id])]
        body = test_client.get(f"{API}/incidents/{incident.id}", headers=_auth(admin)).json()
        assert body["resolvedBy"] == "reader"


# --- personal actions ------------------------------------------------------------


class TestPersonal:
    def test_a_mute_holds_until_its_time_and_keeps_the_read_state(
        self, test_client, db_session, servers, reader, published
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        url = f"{API}/incidents/{incident.id}/mute"
        h = _auth(reader)
        published.clear()

        res = test_client.put(url, headers=h, json={"until": _soon(hours=2)})
        assert res.status_code == 200, res.text
        row = res.json()
        assert (row["muted"], row["muteSource"], row["read"]) == (True, "incident", False)
        assert row["mutedUntil"].endswith("Z")
        assert published == [[reader.id]], "a mute is nobody else's business"
        assert _feed(test_client, admin)[0]["muted"] is False

        res = test_client.delete(url, headers=h)
        assert (res.status_code, res.json()["muted"]) == (200, False)

    @pytest.mark.parametrize(
        "until",
        [
            (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            (datetime.now(timezone.utc) + timedelta(days=7, hours=1)).isoformat(),
            "2026-11-05T12:00:00",
        ],
        ids=["past", "beyond-7-days", "naive"],
    )
    def test_a_mute_lies_in_the_next_seven_days(self, test_client, db_session, servers, until):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        h = _auth(admin)
        res = test_client.put(
            f"{API}/incidents/{incident.id}/mute", headers=h, json={"until": until}
        )
        assert res.status_code == 422, res.text
        server = test_client.put(f"{API}/server-mutes/srv-1", headers=h, json={"until": until})
        assert server.status_code == 422, server.text

    def test_server_mutes(self, test_client, db_session, servers, reader, published):
        ingest(db_session, _check("critical"), now=_at(0))
        ingest(db_session, _heartbeats(["srv-1", "srv-2"]), now=_at(1))
        single, bundle = _incidents(db_session)
        h = _auth(reader)
        hour, two = _soon(hours=1), _soon(hours=2)
        published.clear()

        assert (
            test_client.put(
                f"{API}/server-mutes/srv-2", headers=h, json={"until": hour}
            ).status_code
            == 404
        )
        assert (
            test_client.put(f"{API}/server-mutes/nope", headers=h, json={"until": hour}).status_code
            == 404
        )
        first = test_client.put(f"{API}/server-mutes/srv-1", headers=h, json={"until": hour})
        assert first.status_code == 200, first.text
        second = test_client.put(f"{API}/server-mutes/srv-1", headers=h, json={"until": two})
        assert second.json()["serverId"] == "srv-1"

        listed = test_client.get(f"{API}/server-mutes", headers=h).json()
        assert listed == [second.json()]
        assert published == [[reader.id], [reader.id]]
        rows = {r["incidentId"]: r for r in _feed(test_client, reader)}
        assert (rows[single.id]["muted"], rows[single.id]["muteSource"]) == (True, "server")
        assert rows[single.id]["mutedUntil"] == second.json()["until"]
        assert rows[bundle.id]["muted"] is False, "a bundle row is no single server's"

        for _ in range(2):
            gone = test_client.delete(f"{API}/server-mutes/srv-1", headers=h)
            assert (gone.status_code, gone.content) == (204, b"")
        assert test_client.get(f"{API}/server-mutes", headers=h).json() == []
        assert published == [[reader.id], [reader.id], [reader.id]], "an idle delete nudges nobody"

    def test_a_bundle_of_one_server_is_that_servers(
        self, test_client, db_session, servers, reader, published
    ):
        h = _auth(reader)
        mute = test_client.put(
            f"{API}/server-mutes/srv-1", headers=h, json={"until": _soon(hours=1)}
        )
        assert mute.status_code == 200, mute.text
        checks = _heartbeats(["srv-1"] * 3).model_copy(
            update={"incident_keys": ["check:1", "check:2", "check:3"]}
        )
        ingest(db_session, checks, now=_at(0))
        (incident,) = _incidents(db_session)
        row = _row(db_session, reader, incident)
        assert (row.source_id, row.read_at) == ("srv-1", _at(0)), "the mute held the ping"

        (shown,) = _feed(test_client, reader)
        assert (shown["muted"], shown["muteSource"]) == (True, "server")
        unread = test_client.post(f"{API}/unread", headers=h, json={"ids": [row.id]})
        assert unread.json() == {"updated": 1}
        assert _count(test_client, reader) == 0, "the badge follows the mute of the ping"

    def test_an_admin_mutes_any_server_that_exists(self, test_client, db_session, servers):
        admin = _admin(db_session)
        h = _auth(admin)
        assert (
            test_client.put(
                f"{API}/server-mutes/srv-2", headers=h, json={"until": _soon(hours=1)}
            ).status_code
            == 200
        )
        assert (
            test_client.put(
                f"{API}/server-mutes/nope", headers=h, json={"until": _soon(hours=1)}
            ).status_code
            == 404
        )

    def test_hide_and_unread_touch_only_ones_own_rows(
        self, test_client, db_session, servers, reader, published
    ):
        admin = _admin(db_session)
        ingest(db_session, _check("critical"), now=_at(0))
        (incident,) = _incidents(db_session)
        mine, theirs = _row(db_session, reader, incident), _row(db_session, admin, incident)
        h = _auth(reader)
        published.clear()

        assert test_client.post(f"{API}/hide", headers=h, json={"ids": [theirs.id]}).json() == {
            "updated": 0
        }
        assert (
            test_client.post(f"{API}/read", headers=h, json={"ids": [mine.id]}).status_code == 200
        )
        assert test_client.post(
            f"{API}/unread", headers=h, json={"ids": [mine.id, theirs.id]}
        ).json() == {"updated": 1}
        assert test_client.post(f"{API}/unread", headers=h, json={"ids": [mine.id]}).json() == {
            "updated": 0
        }
        assert _feed(test_client, reader)[0]["read"] is False
        assert published == [[reader.id]]
        db_session.refresh(theirs)
        assert theirs.hidden_at is None

    @pytest.mark.parametrize("route", ["hide", "unread", "incidents/ack"])
    @pytest.mark.parametrize("ids", [[], list(range(1, 502)), [0]], ids=["empty", "501", "zero"])
    def test_id_lists_are_bounded(self, test_client, db_session, servers, route, ids):
        admin = _admin(db_session)
        res = test_client.post(f"{API}/{route}", headers=_auth(admin), json={"ids": ids})
        assert res.status_code == 422, res.text


def test_history_of_an_action_lands_on_the_incident(db_session, servers, test_client):
    admin = _admin(db_session)
    ingest(db_session, _check("critical"), now=_at(0))
    (incident,) = _incidents(db_session)
    test_client.post(f"{API}/incidents/{incident.id}/resolve", headers=_auth(admin))
    entries = (
        db_session.query(NotificationIncidentEvent)
        .filter(NotificationIncidentEvent.incident_id == incident.id)
        .order_by(NotificationIncidentEvent.id)
        .all()
    )
    assert [(e.kind, e.actor_id) for e in entries] == [
        ("triggered", None),
        ("notified", None),
        ("resolved", admin.id),
    ]
