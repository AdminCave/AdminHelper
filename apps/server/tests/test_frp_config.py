# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP server-config resolution (1.30): get_frp_config resolves the singleton
deterministically (oldest first, id tiebreaker) instead of a non-deterministic
.first(), so the agent sync / startup frps.toml never picks a random row."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.modules.frp._helpers import get_frp_config
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.schemas import (
    FrpServerConfigCreate,
    FrpServerConfigUpdate,
    FrpTunnelCreate,
    FrpTunnelUpdate,
)


def _cfg(db, cid: str, created: datetime) -> None:
    db.add(
        FrpServerConfig(
            id=cid,
            name=cid,
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="tok",
            created_at=created,
        )
    )
    db.commit()


def test_get_frp_config_returns_oldest(db_session):
    # Insert the newer row first: a bare .first() could return either.
    _cfg(db_session, "cfg-new", datetime(2024, 1, 1))
    _cfg(db_session, "cfg-old", datetime(2020, 1, 1))
    assert get_frp_config(db_session).id == "cfg-old"


def test_get_frp_config_by_id(db_session):
    _cfg(db_session, "cfg-a", datetime(2020, 1, 1))
    _cfg(db_session, "cfg-b", datetime(2021, 1, 1))
    assert get_frp_config(db_session, "cfg-b").id == "cfg-b"
    assert get_frp_config(db_session, "does-not-exist") is None


def test_get_frp_config_none_when_empty(db_session):
    assert get_frp_config(db_session) is None


def _create_config(db, monkeypatch, **fields):
    from types import SimpleNamespace

    import app.modules.frp.config_router as cr
    from app.modules.frp.schemas import FrpServerConfigCreate

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    monkeypatch.setattr(cr, "fire_event", lambda *a, **k: None)
    data = FrpServerConfigCreate(name="n", server_addr="a.example", **fields)
    cr.create_server_config(data=data, request=SimpleNamespace(state=SimpleNamespace()), db=db)
    return db.query(FrpServerConfig).one()


def test_create_auto_generates_dashboard_password(db_session, monkeypatch):
    # 3.35: dashboard enabled but no password supplied -> generate a strong one,
    # never leave the frps web UI unauthenticated (an empty password emits no
    # webServer.password line at all).
    cfg = _create_config(db_session, monkeypatch, dashboard_port=7500, dashboard_user="admin")
    assert cfg.dashboard_password and len(cfg.dashboard_password) >= 16


def test_create_without_dashboard_leaves_password_none(db_session, monkeypatch):
    # No dashboard -> no password fabricated.
    cfg = _create_config(db_session, monkeypatch)
    assert cfg.dashboard_password is None


def _update_config(db, monkeypatch, config_id, **fields):
    from types import SimpleNamespace

    import app.modules.frp.config_router as cr
    from app.modules.frp.schemas import FrpServerConfigUpdate

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    monkeypatch.setattr(cr, "fire_event", lambda *a, **k: None)
    data = FrpServerConfigUpdate(**fields)
    cr.update_server_config(
        config_id=config_id, data=data, request=SimpleNamespace(state=SimpleNamespace()), db=db
    )
    return db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).one()


def test_update_enabling_dashboard_auto_generates_password(db_session, monkeypatch):
    # 3.35 (update path): enabling the dashboard on a config that had none must
    # generate a password, not leave the frps web UI unauthenticated.
    cfg = _create_config(db_session, monkeypatch)  # no dashboard
    assert cfg.dashboard_password is None
    updated = _update_config(db_session, monkeypatch, cfg.id, dashboard_port=7500)
    assert updated.dashboard_password and len(updated.dashboard_password) >= 16


def test_update_blanking_dashboard_password_regenerates(db_session, monkeypatch):
    # 3.35 (update path): PUT dashboard_password="" on a dashboard-enabled config
    # must regenerate it, not blank it (empty -> no webServer.password line -> open UI).
    cfg = _create_config(db_session, monkeypatch, dashboard_port=7500)
    updated = _update_config(db_session, monkeypatch, cfg.id, dashboard_password="")
    assert updated.dashboard_password and len(updated.dashboard_password) >= 16


def test_update_response_masks_secrets(db_session, monkeypatch):
    # 3.93: the PUT response must not echo auth.token / dashboard_password (the GET
    # invariant), even for an unrelated change like a rename. The config still holds the
    # secrets — they're just not returned in the body.
    from types import SimpleNamespace

    import app.modules.frp.config_router as cr
    from app.modules.frp.schemas import FrpServerConfigUpdate

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    monkeypatch.setattr(cr, "fire_event", lambda *a, **k: None)
    cfg = _create_config(db_session, monkeypatch, dashboard_port=7500, dashboard_user="admin")
    result = cr.update_server_config(
        config_id=cfg.id,
        data=FrpServerConfigUpdate(name="renamed"),
        request=SimpleNamespace(state=SimpleNamespace()),
        db=db_session,
    )
    assert result["authToken"] is None
    assert result["dashboardPassword"] is None
    stored = db_session.query(FrpServerConfig).filter(FrpServerConfig.id == cfg.id).one()
    assert stored.auth_token and stored.dashboard_password  # secrets kept, just not echoed


def test_create_survives_frps_write_failure(db_session, monkeypatch):
    # 4.135: a failed frps.toml write (full/read-only volume) AFTER the commit must NOT turn a
    # committed create into a 500 whose retry would duplicate — the DB is the source of truth and
    # the write is best-effort (like the startup _ensure_frps_config path).
    from types import SimpleNamespace

    import app.modules.frp.config_router as cr
    from app.modules.frp.schemas import FrpServerConfigCreate

    def _boom(config, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(cr, "write_frps_config", _boom)
    monkeypatch.setattr(cr, "fire_event", lambda *a, **k: None)
    data = FrpServerConfigCreate(name="n", server_addr="a.example")
    # Must NOT raise despite the write failure...
    cr.create_server_config(
        data=data, request=SimpleNamespace(state=SimpleNamespace()), db=db_session
    )
    # ...and the config is persisted (DB is the source of truth).
    assert db_session.query(FrpServerConfig).count() == 1


def _login(client, username="admin", password="adminpass"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_list_endpoint_masks_the_auth_token(test_client, db_session, admin_user, monkeypatch):
    # 6.72: the GET /api/frp/server-config list returns to_dict(mask_secrets=True) — the global frps
    # auth.token must never be echoed. The direct-call tests above cover create/update; this pins the
    # HTTP list path, which no test exercised. Dropping the mask would leak the token into every GET.
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    h = _login(test_client)
    created = test_client.post(
        "/api/frp/server-config",
        json={"name": "test-frps", "server_addr": "frps.example.net"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    assert created.json()["authToken"], "create returns the token once, unmasked"

    listed = test_client.get("/api/frp/server-config", headers=h).json()
    assert listed and listed[0]["authToken"] is None, "list must mask the frps auth token"


def test_create_autogenerates_a_strong_auth_token(test_client, db_session, admin_user, monkeypatch):
    # 6.72: an empty auth_token field auto-generates one (secrets.token_urlsafe(32)); frps is never
    # left unauthenticated. Existing tests only cover dashboard_password auto-generation.
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    h = _login(test_client)
    created = test_client.post(
        "/api/frp/server-config",
        json={"name": "test-frps", "server_addr": "frps.example.net"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    token = created.json()["authToken"]
    assert token and len(token) >= 16, f"auto-generated token too weak: {token!r}"


def _create_via_api(client, monkeypatch):
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    h = _login(client)
    created = client.post(
        "/api/frp/server-config",
        json={"name": "test-frps", "server_addr": "frps.example.net"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    return h, created.json()["id"], created.json()["authToken"]


@pytest.mark.parametrize("blank", ["", None])
def test_update_with_a_blank_auth_token_keeps_the_stored_one(
    test_client, db_session, admin_user, monkeypatch, blank
):
    # The GET paths mask the token, so a client sending the field back blank or null means
    # "unchanged"; the other fields of the same PUT still apply.
    h, cid, token = _create_via_api(test_client, monkeypatch)
    updated = test_client.put(
        f"/api/frp/server-config/{cid}",
        json={"name": "renamed", "auth_token": blank},
        headers=h,
    )
    assert updated.status_code == 200, updated.text
    stored = db_session.get(FrpServerConfig, cid)
    db_session.refresh(stored)
    assert stored.auth_token == token
    assert stored.name == "renamed"


def test_update_with_a_new_auth_token_stores_it(test_client, db_session, admin_user, monkeypatch):
    h, cid, _ = _create_via_api(test_client, monkeypatch)
    new_token = "a-new-token-of-sufficient-length"
    updated = test_client.put(
        f"/api/frp/server-config/{cid}", json={"auth_token": new_token}, headers=h
    )
    assert updated.status_code == 200, updated.text
    stored = db_session.get(FrpServerConfig, cid)
    db_session.refresh(stored)
    assert stored.auth_token == new_token


def test_update_with_a_short_auth_token_is_rejected(
    test_client, db_session, admin_user, monkeypatch
):
    h, cid, token = _create_via_api(test_client, monkeypatch)
    updated = test_client.put(
        f"/api/frp/server-config/{cid}", json={"auth_token": "x" * 15}, headers=h
    )
    assert updated.status_code == 422, updated.text
    stored = db_session.get(FrpServerConfig, cid)
    db_session.refresh(stored)
    assert stored.auth_token == token


# --- secrets: 16 characters besides whitespace at either end ---

# Every secret field of the FRP schemas, in the create and in the update schema.
SECRETS = [
    (FrpServerConfigCreate, "auth_token"),
    (FrpServerConfigCreate, "dashboard_password"),
    (FrpServerConfigUpdate, "auth_token"),
    (FrpServerConfigUpdate, "dashboard_password"),
    (FrpTunnelCreate, "secret_key"),
    (FrpTunnelUpdate, "secret_key"),
]
SECRET_IDS = [f"{model.__name__}.{field}" for model, field in SECRETS]
REQUIRED = {
    FrpServerConfigCreate: {"name": "n", "server_addr": "a.example"},
    FrpTunnelCreate: {
        "server_id": "s",
        "frp_config_id": "c",
        "name": "n",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
    },
}
SECRET_RULE = "at least 16 characters besides leading and trailing whitespace"


def _secret(model, field, value):
    return model(**REQUIRED.get(model, {}), **{field: value})


@pytest.mark.parametrize(
    "value",
    [" " * 16, " " + "x" * 15 + " ", "x" * 15 + " " * 4, "\u00a0" * 2 + "x" * 15],
    ids=repr,
)
@pytest.mark.parametrize(("model", "field"), SECRETS, ids=SECRET_IDS)
def test_a_secret_short_of_16_characters_besides_its_ends_is_rejected(model, field, value):
    assert len(value) >= 16
    with pytest.raises(ValidationError, match=SECRET_RULE):
        _secret(model, field, value)


@pytest.mark.parametrize("value", ["abcd efgh ijkl m", "   " + "x" * 16 + " "], ids=repr)
@pytest.mark.parametrize(("model", "field"), SECRETS, ids=SECRET_IDS)
def test_a_secret_of_16_characters_besides_its_ends_is_taken_as_sent(model, field, value):
    assert getattr(_secret(model, field, value), field) == value


@pytest.mark.parametrize("value", ["", None])
@pytest.mark.parametrize(("model", "field"), SECRETS, ids=SECRET_IDS)
def test_an_empty_secret_still_passes(model, field, value):
    # Empty or null skips the check: the routes generate a secret or keep the stored one.
    assert getattr(_secret(model, field, value), field) == value


@pytest.mark.parametrize("field", ["auth_token", "dashboard_password"])
def test_create_with_a_secret_of_spaces_is_rejected(
    test_client, db_session, admin_user, monkeypatch, field
):
    import app.modules.frp.config_router as cr

    monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
    body = {"name": "test-frps", "server_addr": "frps.example.net", "dashboard_port": 7500}
    created = test_client.post(
        "/api/frp/server-config", json={**body, field: " " * 16}, headers=_login(test_client)
    )
    assert created.status_code == 422, created.text
    assert created.json()["detail"][0]["loc"] == ["body", field], created.text
    assert db_session.query(FrpServerConfig).count() == 0


@pytest.mark.parametrize("value", [" " * 16, " " + "x" * 15 + " "], ids=repr)
def test_update_with_an_auth_token_short_of_16_besides_its_ends_is_rejected(
    test_client, db_session, admin_user, monkeypatch, value
):
    h, cid, token = _create_via_api(test_client, monkeypatch)
    updated = test_client.put(
        f"/api/frp/server-config/{cid}", json={"auth_token": value}, headers=h
    )
    assert updated.status_code == 422, updated.text
    stored = db_session.get(FrpServerConfig, cid)
    db_session.refresh(stored)
    assert stored.auth_token == token


def test_update_stores_an_auth_token_with_spaces_at_its_ends_as_sent(
    test_client, db_session, admin_user, monkeypatch
):
    h, cid, _ = _create_via_api(test_client, monkeypatch)
    new_token = "  a-new-token-of-sufficient-length "
    updated = test_client.put(
        f"/api/frp/server-config/{cid}", json={"auth_token": new_token}, headers=h
    )
    assert updated.status_code == 200, updated.text
    stored = db_session.get(FrpServerConfig, cid)
    db_session.refresh(stored)
    assert stored.auth_token == new_token


def _frps_cfg() -> FrpServerConfig:
    return FrpServerConfig(
        id="c1", name="c1", server_addr="frps.example.net", bind_port=7000, auth_token="tok"
    )


def test_write_frps_config_enforces_0600(tmp_path, monkeypatch):
    # 6.147: frps.toml carries the global auth.token + dashboard password and lives in the volume
    # shared with the internet-facing frps container, so it must land 0600 (umask-robust).
    from app.modules.frp import docker_manager

    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", tmp_path)
    path = docker_manager.write_frps_config(_frps_cfg())
    assert path.stat().st_mode & 0o777 == 0o600


def test_write_frps_config_tightens_an_existing_world_readable_file(tmp_path, monkeypatch):
    # An in-place write keeps an existing file's mode; the 0600 temp file (fchmod) swapped in via
    # os.replace must leave no pre-existing 0644 behind — pinned so a refactor back to an in-place
    # write or without the fchmod is caught (6.147).
    from app.modules.frp import docker_manager

    monkeypatch.setattr(docker_manager, "FRP_CONFIG_DIR", tmp_path)
    stale = tmp_path / "frps.toml"
    stale.write_text("old")
    stale.chmod(0o644)
    path = docker_manager.write_frps_config(_frps_cfg())
    assert path.stat().st_mode & 0o777 == 0o600


class TestConfigResponseShape:
    """R-0043: the server-config routes declare FrpServerConfigOut (detail: plus the tunnels).
    Pydantic drops a key the model does not declare without a word, so every body must equal
    what to_dict hands out — the bytes the untyped routes sent."""

    def _expected(self, db, cid, **to_dict_args):
        from fastapi.encoders import jsonable_encoder

        cfg = db.get(FrpServerConfig, cid)
        db.refresh(cfg)
        return jsonable_encoder(cfg.to_dict(**to_dict_args))

    def _sparse_config_with_tunnel(self, db):
        """bind_port NULL, extra_config set, and one tunnel with the nullable columns filled."""
        from app.modules.frp.models import FrpTunnel
        from app.modules.servers.models import Server

        db.add(Server(id="srv-shape", name="shape", hostname="shape.example.test"))
        cfg = FrpServerConfig(
            id="cfg-shape",
            name="shape",
            server_addr="frps.example.net",
            auth_token="a-stored-token-that-is-masked",
            extra_config='{"log.level": "debug", "transport.tcpMux": true}',
        )
        db.add(cfg)
        db.flush()
        # An INSERT with bind_port=None takes the column default (7000); only an UPDATE
        # leaves the NULL a row can hold.
        cfg.bind_port = None
        db.add(
            FrpTunnel(
                id="tun-shape",
                server_id="srv-shape",
                frp_config_id="cfg-shape",
                name="shape-ssh",
                tunnel_type="stcp",
                protocol="ssh",
                local_port=22,
                secret_key="s" * 32,
                visitor_port=6001,
                extra_config='{"transport.useCompression": true}',
                tags='["prod", "edge"]',
            )
        )
        db.commit()
        assert db.get(FrpServerConfig, "cfg-shape").bind_port is None
        return "cfg-shape"

    def test_post_and_list(self, test_client, db_session, admin_user, monkeypatch):
        import app.modules.frp.config_router as cr

        monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
        h = _login(test_client)
        created = test_client.post(
            "/api/frp/server-config",
            json={
                "name": "shape",
                "server_addr": "frps.example.net",
                "dashboard_port": 7500,
                "extra_config": {"log.level": "debug", "transport.tcpMux": True},
            },
            headers=h,
        )
        assert created.status_code == 201, created.text
        cid = created.json()["id"]
        assert created.json() == self._expected(db_session, cid)

        listed = test_client.get("/api/frp/server-config", headers=h)
        assert listed.status_code == 200, listed.text
        assert listed.json() == [self._expected(db_session, cid, mask_secrets=True)]

    def test_sparse_row_through_list_detail_and_put(
        self, test_client, db_session, admin_user, monkeypatch
    ):
        import app.modules.frp.config_router as cr

        monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
        cid = self._sparse_config_with_tunnel(db_session)
        h = _login(test_client)

        listed = test_client.get("/api/frp/server-config", headers=h)
        assert listed.status_code == 200, listed.text
        assert listed.json() == [self._expected(db_session, cid, mask_secrets=True)]
        assert listed.json()[0]["bindPort"] is None

        detail = test_client.get(f"/api/frp/server-config/{cid}", headers=h)
        assert detail.status_code == 200, detail.text
        assert detail.json() == self._expected(
            db_session, cid, include_tunnels=True, mask_secrets=True
        )
        assert [t["id"] for t in detail.json()["tunnels"]] == ["tun-shape"]
        assert detail.json()["tunnels"][0]["secretKey"] is None

        updated = test_client.put(
            f"/api/frp/server-config/{cid}", json={"name": "renamed"}, headers=h
        )
        assert updated.status_code == 200, updated.text
        assert updated.json() == self._expected(db_session, cid, mask_secrets=True)
        assert updated.json()["extraConfig"] == {"log.level": "debug", "transport.tcpMux": True}

    def test_timestamps_are_rfc3339_utc(self, test_client, db_session, admin_user, monkeypatch):
        # format: date-time promises an offset (R-0064): the API writes UTC with Z.
        import app.modules.frp.config_router as cr

        monkeypatch.setattr(cr, "write_frps_config", lambda config, **kwargs: None)
        cid = self._sparse_config_with_tunnel(db_session)
        db_session.get(FrpServerConfig, cid).updated_at = datetime(2026, 10, 5, 12, 0, 0)
        db_session.commit()
        h = _login(test_client)

        detail = test_client.get(f"/api/frp/server-config/{cid}", headers=h)
        assert detail.status_code == 200, detail.text
        assert detail.json()["createdAt"].endswith("Z"), detail.text
        assert detail.json()["updatedAt"] == "2026-10-05T12:00:00Z"
        assert detail.json()["tunnels"][0]["createdAt"].endswith("Z"), detail.text
