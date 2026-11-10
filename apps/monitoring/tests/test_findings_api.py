# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The admin API of the module catalog (R-1223): the catalog, a server's discovery with
"scan now", and the findings inbox with adopt, adopt all and dismiss."""

import json
from datetime import datetime, timedelta

import pytest

from app import module_sync
from app.catalog.loader import get_catalog
from app.models import MonitorCheck, MonitorDiscovery, MonitorFinding
from app.module_sync import sync_catalog
from app.routers import findings as findings_router

from .test_module_sync import (
    CONTAINERS,
    NO_PAPERLESS,
    PROJECT_SUMMARY,
    V1,
    WITH_HEALTH,
    WITHOUT_BROKER,
)

T0 = datetime(2020, 1, 1, 12, 0)


@pytest.fixture()
def catalog(monkeypatch):
    """Sets the catalog the routes see."""

    def use(cat):
        monkeypatch.setattr(findings_router, "get_catalog", lambda: cat)

    use(V1)
    return use


def _finding(factory, module_id="paperless", key="paperless", *, server_id="srv-1", **kw):
    with factory() as db:
        finding = MonitorFinding(
            id=f"f-{server_id}-{module_id}-{key}",
            server_id=server_id,
            module_id=module_id,
            instance_key=key,
            kind=kw.get("kind", "new"),
            status=kw.get("status", "open"),
            summary=json.dumps(kw.get("summary", PROJECT_SUMMARY)),
            catalog_version="before",
            first_seen=T0,
            last_seen=T0 + timedelta(hours=1),
        )
        db.add(finding)
        db.commit()
        return finding.id


def _inventory(factory, server_id="srv-1", **kw):
    with factory() as db:
        db.add(
            MonitorDiscovery(
                server_id=server_id,
                inventory=json.dumps({"containers": CONTAINERS}),
                **kw,
            )
        )
        db.commit()


def test_catalog_of_the_running_service(client_db):
    client, _ = client_db

    body = client.get("/catalog").json()

    assert body["version"] == get_catalog().version
    port = next(m for m in body["modules"] if m["id"] == "port")
    assert port["instance"] == "port"
    assert port["checks"][0]["key"] == "answers"
    assert port["checks"][0]["credential"] is None


def test_catalog_shape(client_db, catalog):
    client, _ = client_db

    body = client.get("/catalog").json()

    assert body["version"] == V1.version
    assert [m["id"] for m in body["modules"]] == ["nginx", "paperless", "port"]
    paperless = body["modules"][1]
    assert set(paperless) == {
        "id",
        "name",
        "version",
        "description",
        "instance",
        "checks",
        "card",
    }
    assert paperless["checks"][0] == {
        "key": "web",
        "name": "Web",
        "sensor": "http",
        "interval": 300,
        "fields": ["status_code"],
        "testObject": False,
        "credential": {"slot": "api", "use": "bearer"},
    }


def test_discovery_before_any_scan(client_db):
    client, _ = client_db

    assert client.get("/discovery/srv-9").json() == {
        "serverId": "srv-9",
        "scannedAt": None,
        "nextScanAt": None,
        "scanRequestedAt": None,
        "inventory": {},
        "credentials": [],
    }


def test_discovery_of_a_scanned_server(client_db):
    client, factory = client_db
    _inventory(
        factory,
        scanned_at=T0,
        next_scan_at=T0 + timedelta(days=1),
        credentials=json.dumps({"redis/cache/default": True, "paperless/paperless/api": True}),
    )

    body = client.get("/discovery/srv-1").json()

    assert body["scannedAt"] == "2020-01-01T12:00:00Z"
    assert body["nextScanAt"] == "2020-01-02T12:00:00Z"
    assert body["inventory"] == {"containers": CONTAINERS}
    assert body["credentials"] == ["paperless/paperless/api", "redis/cache/default"]


def test_scan_now_is_asked_once(client_db, monkeypatch):
    client, factory = client_db
    clock = iter([T0, T0 + timedelta(minutes=5)])
    monkeypatch.setattr(findings_router, "utcnow_naive", lambda: next(clock))

    first = client.post("/discovery/srv-1/scan")
    again = client.post("/discovery/srv-1/scan")

    assert first.status_code == again.status_code == 200
    assert first.json()["scanRequestedAt"] == "2020-01-01T12:00:00Z"
    assert again.json() == first.json()
    with factory() as db:
        assert db.get(MonitorDiscovery, "srv-1").scan_requested_at == T0


def test_scan_now_on_a_scanned_server(client_db, monkeypatch):
    client, factory = client_db
    _inventory(factory, scanned_at=T0)
    monkeypatch.setattr(findings_router, "utcnow_naive", lambda: T0 + timedelta(hours=2))

    body = client.post("/discovery/srv-1/scan").json()

    assert body["scanRequestedAt"] == "2020-01-01T14:00:00Z"
    assert body["inventory"] == {"containers": CONTAINERS}


def test_findings_inbox(client_db, catalog):
    client, factory = client_db
    _finding(factory)
    _finding(factory, "nginx", "nginx.service", status="dismissed", summary={})
    _finding(factory, server_id="srv-2")

    body = client.get("/findings").json()

    assert [(f["serverId"], f["moduleId"]) for f in body] == [
        ("srv-1", "nginx"),
        ("srv-1", "paperless"),
        ("srv-2", "paperless"),
    ]
    assert body[1] == {
        "id": "f-srv-1-paperless-paperless",
        "serverId": "srv-1",
        "moduleId": "paperless",
        "moduleName": "Paperless",
        "instanceKey": "paperless",
        "kind": "new",
        "status": "open",
        "summary": PROJECT_SUMMARY,
        "catalogVersion": "before",
        "firstSeen": "2020-01-01T12:00:00Z",
        "lastSeen": "2020-01-01T13:00:00Z",
        "decidedAt": None,
        "silentChecks": [],
        "droppedChecks": [],
    }
    open_srv1 = client.get("/findings", params={"server_id": "srv-1", "status": "open"}).json()
    assert [f["moduleId"] for f in open_srv1] == ["paperless"]

    page = client.get("/findings", params={"limit": 1, "offset": 1})
    assert page.headers["X-Total-Count"] == "3"
    assert [f["serverId"] for f in page.json()] == ["srv-1"]


@pytest.mark.parametrize(
    "params", [{"status": "gone"}, {"limit": 0}, {"limit": 1001}, {"offset": -1}]
)
def test_findings_inbox_rejects_bad_parameters(client_db, params):
    client, _ = client_db

    assert client.get("/findings", params=params).status_code == 422


def test_adopt_and_the_checks_it_made(client_db, catalog):
    client, factory = client_db
    _inventory(factory)
    finding_id = _finding(factory)

    r = client.post(f"/findings/{finding_id}/adopt")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["finding"]["status"] == "adopted"
    assert body["finding"]["catalogVersion"] == V1.version
    assert len(body["enabledChecks"]) == 2
    assert body["disabledChecks"] == []
    assert body["skippedChecks"] == [{"key": "sched", "reason": "no unit for this instance"}]
    checks = client.get("/checks", params={"server_id": "srv-1"}).json()
    assert sorted(c["id"] for c in checks) == sorted(body["enabledChecks"])
    for check in checks:
        assert (
            check["checkType"],
            check["moduleId"],
            check["moduleInstance"],
            check["silent"],
        ) == (
            "probe",
            "paperless",
            "paperless",
            False,
        )


def test_adopt_a_module_the_catalog_lost(client_db, catalog):
    client, factory = client_db
    finding_id = _finding(factory)
    catalog(NO_PAPERLESS)

    r = client.post(f"/findings/{finding_id}/adopt")

    assert (r.status_code, r.json()["detail"]) == (409, "Module is no longer in the catalog")
    assert client.get("/findings").json()[0]["status"] == "open"


@pytest.mark.parametrize("action", ["adopt", "dismiss"])
def test_unknown_finding(client_db, action):
    client, _ = client_db

    r = client.post(f"/findings/nope/{action}")

    assert (r.status_code, r.json()["detail"]) == (404, "Finding not found")


def test_adopt_all(client_db, catalog):
    client, factory = client_db
    _inventory(factory)
    project = _finding(factory)
    lost = _finding(factory, "lost", "lost")
    other = _finding(factory, server_id="srv-2")

    assert client.post("/findings/adopt-all").status_code == 422
    body = client.post("/findings/adopt-all", params={"server_id": "srv-1"}).json()

    assert [a["finding"]["id"] for a in body["adopted"]] == [project]
    assert body["failed"] == [{"findingId": lost, "reason": "Module is no longer in the catalog"}]
    statuses = {f["id"]: f["status"] for f in client.get("/findings").json()}
    assert statuses == {project: "adopted", lost: "open", other: "open"}


def test_dismiss(client_db, catalog, monkeypatch):
    client, factory = client_db
    finding_id = _finding(factory)
    monkeypatch.setattr(module_sync, "utcnow_naive", lambda: T0 + timedelta(days=1))

    body = client.post(f"/findings/{finding_id}/dismiss").json()

    assert (body["status"], body["decidedAt"]) == ("dismissed", "2020-01-02T12:00:00Z")


def test_silent_and_dropped_checks_of_a_finding(client_db, catalog):
    client, factory = client_db
    _inventory(factory)
    finding_id = _finding(factory)
    assert client.post(f"/findings/{finding_id}/adopt").status_code == 200
    with factory() as db:
        sync_catalog(db, catalog=WITH_HEALTH)
        ids = {c.module_check_key: c.id for c in db.query(MonitorCheck)}
    catalog(WITH_HEALTH)

    (finding,) = client.get("/findings").json()

    assert (finding["kind"], finding["status"]) == ("changed", "open")
    assert finding["silentChecks"] == [ids["health"]]
    assert finding["droppedChecks"] == []

    # Neither broker nor the health check the sync added are in this catalog.
    catalog(WITHOUT_BROKER)
    dropped = client.get("/findings").json()[0]["droppedChecks"]
    assert sorted(dropped) == sorted([ids["broker"], ids["health"]])

    catalog(NO_PAPERLESS)
    (finding,) = client.get("/findings").json()
    assert finding["moduleName"] is None
    assert sorted(finding["droppedChecks"]) == sorted(ids.values())
