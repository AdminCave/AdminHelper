# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /api/internal/servers (T8): service-to-service inventory listing for the
monitoring tag-sync. Same fail-closed X-Internal-Key gate as /api/internal/events;
payload is deliberately minimal (id, hostname, name, tags)."""

import json

from app.modules.servers.models import Server

_PATH = "/api/internal/servers"


def _server(db, sid: str, tags: list[str] | None = None):
    db.add(
        Server(
            id=sid,
            name=f"name-{sid}",
            hostname=f"host-{sid}",
            os_type="linux",
            tags=json.dumps(tags) if tags else None,
            notes="",
        )
    )
    db.commit()


class TestInternalServers:
    def test_missing_key_rejected(self, test_client):
        assert test_client.get(_PATH).status_code == 403

    def test_wrong_key_rejected(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "right")
        assert test_client.get(_PATH, headers={"X-Internal-Key": "wrong"}).status_code == 403

    def test_blank_configured_key_is_fail_closed(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "")
        assert test_client.get(_PATH, headers={"X-Internal-Key": ""}).status_code == 403

    def test_lists_minimal_shape_with_tags(self, test_client, db_session, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "secret")
        _server(db_session, "srv-a", tags=["web", "prod"])
        _server(db_session, "srv-b")

        res = test_client.get(_PATH, headers={"X-Internal-Key": "secret"})
        assert res.status_code == 200
        payload = {s["id"]: s for s in res.json()}
        assert payload["srv-a"] == {
            "id": "srv-a",
            "hostname": "host-srv-a",
            "name": "name-srv-a",
            "tags": ["web", "prod"],
        }
        # No tags stored -> empty list, and no extra fields leak (notes etc.).
        assert payload["srv-b"]["tags"] == []
        assert set(payload["srv-b"].keys()) == {"id", "hostname", "name", "tags"}
