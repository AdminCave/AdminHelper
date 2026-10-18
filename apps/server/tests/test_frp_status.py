# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /api/frp/status (6.148). The endpoint has real logic that only surfaced live against a real frps
before: 404 without a config, 400 without a dashboard port, and — crucially — an unreachable dashboard
must return a 200 error payload rather than throwing. pytest-httpx stubs the dashboard request.

Without FRPS_DASHBOARD_URL the route asks no dashboard: it reads the proxy lists the frps supervisor
puts into FRPS_STATE_DIR (proxy-<type>.json), and only a current, valid one counts; with none of
them it answers with the error payload, never a 500."""

import json
import os
import time

import httpx
import pytest

from app.modules.frp.models import FrpServerConfig


def _login(test_client):
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _config(db, **over):
    fields = dict(id="c1", name="c1", server_addr="frps.example", bind_port=7000, auth_token="tok")
    fields.update(over)
    db.add(FrpServerConfig(**fields))
    db.commit()


def test_status_404_without_config(test_client, admin_user, db_session):
    resp = test_client.get("/api/frp/status", headers=_login(test_client))
    assert resp.status_code == 404


def test_status_400_without_dashboard_port(test_client, admin_user, db_session):
    _config(db_session, dashboard_port=None)
    resp = test_client.get("/api/frp/status", headers=_login(test_client))
    assert resp.status_code == 400


def test_status_unreachable_dashboard_returns_error_payload(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    # Pin a single dashboard candidate so exactly one request is made, then make it refuse to connect.
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", "http://frps-test:7500")
    _config(db_session, dashboard_port=7500)
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    resp = test_client.get("/api/frp/status", headers=_login(test_client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["proxies"] == []
    assert "nicht erreichbar" in body["error"]


_DASHBOARD = "http://frps-test:7500"


def test_status_body_equals_the_untyped_dict(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    """R-0043: the route declares FrpStatus. One proxy from the stubbed dashboard, matched to
    a tunnel: the body must be exactly the dict the untyped route built — every proxy key, the
    tunnel as to_dict() hands it out, and no `error` key on success."""
    from fastapi.encoders import jsonable_encoder

    import app.modules.frp.status_router as sr
    from app.modules.frp.models import FrpTunnel
    from app.modules.servers.models import Server

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    _config(db_session, dashboard_port=7500)
    db_session.add(Server(id="srv-st", name="st", hostname="st.example.test"))
    db_session.add(
        FrpTunnel(
            id="tun-st",
            server_id="srv-st",
            frp_config_id="c1",
            name="st-ssh",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            tags='["prod"]',
        )
    )
    db_session.commit()
    proxy = {
        "name": "admin.st-ssh",
        "status": "online",
        "curConns": 2,
        "todayTrafficIn": 1024,
        "todayTrafficOut": 2048,
        "lastStartTime": "09-27 10:00:00",
        "lastCloseTime": "",
    }
    httpx_mock.add_response(url=f"{_DASHBOARD}/api/proxy/stcp", json={"proxies": [proxy]})
    for proxy_type in ("https", "tcp", "udp"):
        httpx_mock.add_response(url=f"{_DASHBOARD}/api/proxy/{proxy_type}", json={"proxies": []})

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    tunnel = db_session.get(FrpTunnel, "tun-st")
    assert resp.json() == {
        "proxies": [
            {
                "name": "admin.st-ssh",
                "type": "stcp",
                "status": "online",
                "curConns": 2,
                "clientVersion": "",
                "todayTrafficIn": 1024,
                "todayTrafficOut": 2048,
                "lastStartTime": "09-27 10:00:00",
                "lastCloseTime": "",
                "tunnel": jsonable_encoder(tunnel.to_dict()),
            }
        ],
        "total": 1,
    }
    assert resp.json()["proxies"][0]["tunnel"]["secretKey"] is None


def test_status_masks_the_tunnel_secret(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    """The matched tunnel is handed out without its secret: the status page never needs it."""
    import app.modules.frp.status_router as sr
    from app.modules.frp.models import FrpTunnel
    from app.modules.servers.models import Server

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    _config(db_session, dashboard_port=7500)
    db_session.add(Server(id="srv-sec", name="sec", hostname="sec.example.test"))
    db_session.add(
        FrpTunnel(
            id="tun-sec",
            server_id="srv-sec",
            frp_config_id="c1",
            name="sec-ssh",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key="s" * 32,
        )
    )
    db_session.commit()
    httpx_mock.add_response(
        url=f"{_DASHBOARD}/api/proxy/stcp",
        json={"proxies": [{"name": "admin.sec-ssh", "status": "online"}]},
    )
    for proxy_type in ("https", "tcp", "udp"):
        httpx_mock.add_response(url=f"{_DASHBOARD}/api/proxy/{proxy_type}", json={"proxies": []})

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    tunnel = resp.json()["proxies"][0]["tunnel"]
    assert tunnel["id"] == "tun-sec"
    assert tunnel["secretKey"] is None


def test_status_unreachable_body_equals_the_untyped_dict(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    """The error answer keeps its three keys, nothing more (an unset `error` is dropped, a set
    one is not)."""
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    _config(db_session, dashboard_port=7500)
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "proxies": [],
        "total": 0,
        "error": "frps-Dashboard: nicht erreichbar (ConnectError)",
    }


# --- without FRPS_DASHBOARD_URL: the proxy lists of the frps supervisor ---

_NO_DATA = {
    "proxies": [],
    "total": 0,
    "error": "frps dashboard: no current data from the frps supervisor",
}


def _supervisor(monkeypatch, state_dir):
    """The route without FRPS_DASHBOARD_URL, its state directory at state_dir."""
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", "")
    monkeypatch.setattr(sr, "FRPS_STATE_DIR", state_dir)


def _tunnel(db, name: str):
    from app.modules.frp.models import FrpTunnel
    from app.modules.servers.models import Server

    db.add(Server(id=f"srv-{name}", name=name, hostname=f"{name}.example.test"))
    db.add(
        FrpTunnel(
            id=f"tun-{name}",
            server_id=f"srv-{name}",
            frp_config_id="c1",
            name=name,
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key="s" * 32,
        )
    )
    db.commit()
    return db.get(FrpTunnel, f"tun-{name}")


def _list(*proxies: dict) -> bytes:
    return json.dumps({"proxies": list(proxies)}).encode()


# A proxy as frps 0.69.1 lists it (ProxyStatsInfo), conf included, which the view leaves out.
_PROXY = {
    "name": "srv1.sup-ssh",
    "conf": {"name": "srv1.sup-ssh", "type": "stcp"},
    "clientVersion": "0.69.1",
    "todayTrafficIn": 1024,
    "todayTrafficOut": 2048,
    "curConns": 2,
    "lastStartTime": "10-18 07:00:00",
    "lastCloseTime": "",
    "status": "online",
}


def test_status_without_dashboard_url_reads_the_supervisor_files(
    test_client, admin_user, db_session, httpx_mock, monkeypatch, tmp_path
):
    """No request goes out (httpx_mock has none to give); the proxy comes from proxy-stcp.json,
    matched to its tunnel, the secret masked."""
    from fastapi.encoders import jsonable_encoder

    _supervisor(monkeypatch, tmp_path)
    _config(db_session, dashboard_port=7500)
    tunnel = _tunnel(db_session, "sup-ssh")
    (tmp_path / "proxy-stcp.json").write_bytes(_list(_PROXY))
    for proxy_type in ("https", "tcp", "udp"):
        (tmp_path / f"proxy-{proxy_type}.json").write_bytes(_list())

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "proxies": [
            {
                "name": "srv1.sup-ssh",
                "type": "stcp",
                "status": "online",
                "curConns": 2,
                "clientVersion": "0.69.1",
                "todayTrafficIn": 1024,
                "todayTrafficOut": 2048,
                "lastStartTime": "10-18 07:00:00",
                "lastCloseTime": "",
                "tunnel": jsonable_encoder(tunnel.to_dict(mask_secrets=True)),
            }
        ],
        "total": 1,
    }
    assert resp.json()["proxies"][0]["tunnel"]["secretKey"] is None


def test_status_takes_the_type_from_the_file_and_leaves_out_one_without_a_current_list(
    test_client, admin_user, db_session, monkeypatch, tmp_path
):
    _supervisor(monkeypatch, tmp_path)
    _config(db_session, dashboard_port=7500)
    # What the proxy says of its type counts for nothing; a key the view shows may be absent.
    (tmp_path / "proxy-tcp.json").write_bytes(_list({"name": "srv1.db", "type": "udp"}))
    (tmp_path / "proxy-udp.json").write_bytes(_list(_PROXY))
    _age(tmp_path / "proxy-udp.json", 61)

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "proxies": [
            {
                "name": "srv1.db",
                "type": "tcp",
                "status": "unknown",
                "curConns": 0,
                "clientVersion": "",
                "todayTrafficIn": 0,
                "todayTrafficOut": 0,
                "lastStartTime": "",
                "lastCloseTime": "",
                "tunnel": None,
            }
        ],
        "total": 1,
    }


def _age(path, seconds: int):
    """Sets the mtime of path seconds into the past (without following a symlink)."""
    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)


def _write(content: bytes):
    return lambda path: path.write_bytes(content)


def _stale(seconds: int):
    def damage(path):
        path.write_bytes(_list(_PROXY))
        _age(path, seconds)

    return damage


def _padded(size: int):
    """A valid list padded with blanks to size bytes."""
    return lambda path: path.write_bytes(_list(_PROXY).ljust(size))


def _symlink(path):
    target = path.with_name("elsewhere.json")
    target.write_bytes(_list(_PROXY))
    path.symlink_to(target)


def _proxy_with(**fields) -> bytes:
    return _list({**_PROXY, **fields})


# Each leaves proxy-stcp.json the one list there is, and no current, valid one.
_NOT_USABLE = {
    "61 s old": _stale(61),
    "a byte over 1 MiB": _padded(1024 * 1024 + 1),
    "no JSON": _write(b"proxies: none\n"),
    "no UTF-8": _write(b'{"proxies": [{"name": "srv1.\xff"}]}'),
    "duplicate key": _write(b'{"proxies": [], "proxies": []}'),
    # Strict JSON also in a key the view leaves out.
    "NaN": _write(b'{"proxies": [{"name": "srv1.x", "conf": NaN}]}'),
    "nested too deep": _write(b'{"proxies": [' + b"[" * 100_000 + b"]" * 100_000 + b"]}"),
    "a list, no object": _write(b"[]"),
    "no proxies": _write(b'{"proxy": []}'),
    "proxies no list": _write(b'{"proxies": {"name": "srv1.x"}}'),
    "a proxy no object": _write(b'{"proxies": ["srv1.x"]}'),
    "name a number": _write(_proxy_with(name=7)),
    "curConns a string": _write(_proxy_with(curConns="2")),
    "curConns true": _write(_proxy_with(curConns=True)),
    "todayTrafficIn a float": _write(_proxy_with(todayTrafficIn=1.5)),
    "status null": _write(_proxy_with(status=None)),
    "a lone surrogate": _write(b'{"proxies": [{"name": "srv1.\\ud800"}]}'),
    "a symlink": _symlink,
    "a FIFO": os.mkfifo,
    "a directory": lambda path: path.mkdir(),
}


@pytest.mark.parametrize("case", list(_NOT_USABLE))
def test_status_without_a_current_valid_list_answers_with_the_error(
    test_client, admin_user, db_session, monkeypatch, tmp_path, case
):
    _supervisor(monkeypatch, tmp_path)
    _config(db_session, dashboard_port=7500)
    _NOT_USABLE[case](tmp_path / "proxy-stcp.json")

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json() == _NO_DATA


@pytest.mark.parametrize("missing", ["no file", "no state directory"])
def test_status_without_any_list_answers_with_the_error(
    test_client, admin_user, db_session, monkeypatch, tmp_path, missing
):
    _supervisor(monkeypatch, tmp_path if missing == "no file" else tmp_path / "none")
    _config(db_session, dashboard_port=7500)

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json() == _NO_DATA


@pytest.mark.parametrize("case", ["59 s old", "1 MiB"], ids=["59 s old", "1 MiB"])
def test_status_takes_a_list_just_inside_the_limits(
    test_client, admin_user, db_session, monkeypatch, tmp_path, case
):
    _supervisor(monkeypatch, tmp_path)
    _config(db_session, dashboard_port=7500)
    path = tmp_path / "proxy-stcp.json"
    (_stale(59) if case == "59 s old" else _padded(1024 * 1024))(path)

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert "error" not in resp.json()
    assert [p["name"] for p in resp.json()["proxies"]] == ["srv1.sup-ssh"]


def test_status_with_dashboard_url_asks_the_dashboard_not_the_files(
    test_client, admin_user, db_session, httpx_mock, monkeypatch, tmp_path
):
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    monkeypatch.setattr(sr, "FRPS_STATE_DIR", tmp_path)
    _config(db_session, dashboard_port=7500)
    (tmp_path / "proxy-stcp.json").write_bytes(_list(_PROXY))
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json()["error"] == "frps-Dashboard: nicht erreichbar (ConnectError)"
