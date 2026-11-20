# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /objects (R-1559): the objects of the checks with their damped state, worst
first, with filters, paging and the time of the check's last run."""

from datetime import datetime, timedelta

import pytest

from app.checkers.plugins import DockerHealthChecker, ProxmoxBackupChecker
from app.models import MonitorCheck, MonitorObjectState, MonitorState
from app.objects import NOT_COLLECTED, object_key, read_objects

T0 = datetime(2026, 11, 19, 12, 0, 0)
MIN = timedelta(minutes=1)


def _check(db, ident, server_id="srv-1", name=None):
    db.add(
        MonitorCheck(
            id=ident,
            server_id=server_id,
            name=name or ident,
            check_type="ping",
            config="{}",
            enabled=True,
        )
    )


def _object(db, check_id, ident, status="ok", *, kind="disk", name=None, **cols):
    server = cols.pop("server", "srv-1")
    values = {
        "check_id": check_id,
        "object_key": object_key(server, kind, ident),
        "kind": kind,
        "name": name or ident,
        "status": status,
        "reason": f"{status} reason",
        "since": T0,
        "bad_since": None,
        "fail_count": 0,
        "stable": True,
        "gone_at": None,
    }
    values.update(cols)
    db.add(MonitorObjectState(**values))


@pytest.fixture()
def objects(client_db):
    client, factory = client_db
    with factory() as db:
        _check(db, "c1", name="Disks")
        _check(db, "c2", server_id="srv-2", name="Services")
        db.flush()
        db.add(MonitorState(check_id="c1", status="critical", since=T0, last_check=T0 + 5 * MIN))
        _object(db, "c1", "sda", "critical", bad_since=T0 - MIN, stable=False)
        _object(db, "c1", "sdb")
        _object(db, "c1", "sdc", "warning", gone_at=T0 + MIN)
        _object(db, "c2", "nginx", NOT_COLLECTED, kind="service", server="srv-2")
        db.commit()
    return client, factory


def _keys(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [entry["key"] for entry in response.json()]


def test_an_object_carries_its_state_its_check_and_the_last_run(objects):
    client, _ = objects
    r = client.get("/objects", params={"check_id": "c1"})

    assert r.status_code == 200, r.text
    assert r.json()[0] == {
        "checkId": "c1",
        "checkName": "Disks",
        "serverId": "srv-1",
        "key": "srv-1/disk/sda",
        "kind": "disk",
        "name": "sda",
        "status": "critical",
        "reason": "critical reason",
        "since": "2026-11-19T12:00:00Z",
        "badSince": "2026-11-19T11:59:00Z",
        "stable": False,
        "goneAt": None,
        "lastCheck": "2026-11-19T12:05:00Z",
    }


def test_a_check_without_a_run_has_no_last_check(objects):
    client, _ = objects
    (entry,) = client.get("/objects", params={"check_id": "c2"}).json()
    assert (entry["key"], entry["lastCheck"], entry["serverId"]) == (
        "srv-2/service/nginx",
        None,
        "srv-2",
    )


def test_gone_objects_show_only_on_request(objects):
    client, _ = objects
    assert "srv-1/disk/sdc" not in _keys(client.get("/objects"))

    r = client.get("/objects", params={"include_gone": "true"})
    gone = [entry for entry in r.json() if entry["key"] == "srv-1/disk/sdc"]
    assert [entry["goneAt"] for entry in gone] == ["2026-11-19T12:01:00Z"]


def test_objects_come_worst_first_then_by_name(client_db):
    client, factory = client_db
    with factory() as db:
        _check(db, "c1")
        _check(db, "c2")
        db.flush()
        # Names against the severity: the order must come from the status.
        _object(db, "c1", "a-ok")
        _object(db, "c1", "b-collected", NOT_COLLECTED)
        _object(db, "c1", "c-info", "info")
        _object(db, "c1", "d-unknown", "unknown")
        _object(db, "c1", "e-warning", "warning")
        _object(db, "c1", "f-critical", "critical")
        # A status the object vocabulary does not know counts as the worst.
        _object(db, "c1", "g-strange", "strange")
        # Same status: by name, across checks.
        _object(db, "c2", "a-critical", "critical")
        db.commit()

    assert _keys(client.get("/objects")) == [
        "srv-1/disk/a-critical",
        "srv-1/disk/f-critical",
        "srv-1/disk/g-strange",
        "srv-1/disk/e-warning",
        "srv-1/disk/d-unknown",
        "srv-1/disk/c-info",
        "srv-1/disk/b-collected",
        "srv-1/disk/a-ok",
    ]


@pytest.mark.parametrize(
    "params, keys",
    [
        ({"server_id": "srv-2"}, ["srv-2/service/nginx"]),
        ({"check_id": "c1"}, ["srv-1/disk/sda", "srv-1/disk/sdb"]),
        ({"kind": "service"}, ["srv-2/service/nginx"]),
        ({"server_id": "srv-1", "kind": "service"}, []),
        (
            {"server_id": "srv-1", "include_gone": "true"},
            ["srv-1/disk/sda", "srv-1/disk/sdc", "srv-1/disk/sdb"],
        ),
    ],
    ids=["server", "check", "kind", "combined", "server-with-gone"],
)
def test_filters_narrow_the_objects(objects, params, keys):
    client, _ = objects
    assert _keys(client.get("/objects", params=params)) == keys


def test_without_a_filter_every_object_that_is_not_gone(objects):
    client, _ = objects
    assert _keys(client.get("/objects")) == [
        "srv-1/disk/sda",
        "srv-2/service/nginx",
        "srv-1/disk/sdb",
    ]


def test_paging_slices_and_counts_the_filtered_objects(objects):
    client, _ = objects
    r = client.get("/objects", params={"limit": 1, "offset": 1})
    assert _keys(r) == ["srv-2/service/nginx"]
    assert r.headers["X-Total-Count"] == "3"

    r = client.get("/objects", params={"check_id": "c1", "include_gone": "true", "limit": 2})
    assert _keys(r) == ["srv-1/disk/sda", "srv-1/disk/sdc"]
    assert r.headers["X-Total-Count"] == "3"

    r = client.get("/objects")
    assert r.headers["X-Total-Count"] == "3"


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 1001}, {"offset": -1}, {"include_gone": "maybe"}],
    ids=["limit-0", "limit-over", "offset-negative", "gone-not-bool"],
)
def test_bad_query_values_are_refused(objects, params):
    client, _ = objects
    assert client.get("/objects", params=params).status_code == 422


def test_a_central_check_has_no_server(client_db):
    client, factory = client_db
    with factory() as db:
        _check(db, "c1", server_id=None, name="DNS")
        _check(db, "c2", name="Disks")
        db.flush()
        _object(db, "c1", "example.org", kind="dns", server=None)
        _object(db, "c2", "sda")
        db.commit()

    r = client.get("/objects", params={"kind": "dns"})
    (entry,) = r.json()
    assert (entry["key"], entry["serverId"], entry["checkName"]) == ("dns/example.org", None, "DNS")
    # A server filter keeps the server's objects and leaves the central check out.
    assert _keys(client.get("/objects", params={"server_id": "srv-1"})) == ["srv-1/disk/sda"]


def test_objects_need_the_internal_key(client_db, monkeypatch):
    from app.core import auth
    from app.main import app

    app.dependency_overrides.pop(auth.require_internal)
    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "internal-secret")
    client, _ = client_db

    assert client.get("/objects").status_code == 401
    assert client.get("/objects", headers={"X-Internal-Key": "wrong"}).status_code == 401
    # Paired: the right key passes.
    assert client.get("/objects", headers={"X-Internal-Key": "internal-secret"}).status_code == 200


def test_compose_containers_and_cluster_guests_get_host_kind_and_stable_id_keys():
    docker = {
        "docker": {
            "available": True,
            "error": None,
            "containers": [
                {
                    "id": "abc123def456",
                    "name": "shop-web-2",
                    "state": "running",
                    "compose_project": "shop",
                    "compose_service": "web",
                    "compose_number": 2,
                }
            ],
        }
    }
    proxmox = {
        "proxmox": {
            "available": True,
            "error": None,
            "cluster_name": "pve-c1",
            "vms": [{"vmid": 100, "status": "stopped"}],
        }
    }
    _, _, containers = DockerHealthChecker().evaluate({}, docker)
    _, _, guests = ProxmoxBackupChecker().evaluate({}, proxmox)
    _, by_key = read_objects(containers["_objects"], "srv-1")
    assert list(by_key) == ["srv-1/container/shop/web/2"]
    assert by_key["srv-1/container/shop/web/2"]["stable"] is True
    _, by_key = read_objects(guests["_objects"], "srv-1")
    assert list(by_key) == ["srv-1/guest-backup/pve-c1/100"]
    assert by_key["srv-1/guest-backup/pve-c1/100"]["stable"] is True
