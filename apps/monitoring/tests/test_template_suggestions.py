# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template suggestions from the agent's host facts (R-0421): the schema that keeps
what a server's agent last reported about its host and which suggestions an admin
ignored, the server cleanup that takes both with it, and the two routes that list
a server's suggestions and ignore one."""

import json
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.builtin_templates import seed_builtin_templates
from app.models import (
    Base,
    MonitorAgentKey,
    MonitorHostFacts,
    MonitorTemplate,
    MonitorTemplateAssignment,
    MonitorTemplateSuggestionDismissal,
)
from app.server_cleanup import cleanup_server
from app.template_suggestions import SUGGESTED_SLUGS


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _dismissal(server_id="srv-1", slug="linux-base"):
    return MonitorTemplateSuggestionDismissal(
        id=str(uuid.uuid4()), server_id=server_id, builtin_slug=slug
    )


# --- schema ---------------------------------------------------------------------


def test_host_facts_row_starts_without_subsystems(db):
    # Raw SQL: the ORM would fill subsystems from its own default, so only an insert
    # past it shows the column's server default.
    db.execute(text("INSERT INTO monitor_host_facts (server_id) VALUES ('srv-1')"))
    db.commit()

    facts = db.get(MonitorHostFacts, "srv-1")
    assert facts.subsystems == "[]"
    assert facts.os is None
    assert facts.updated_at is not None


def test_second_dismissal_of_the_same_suggestion_is_rejected(db):
    db.add(_dismissal())
    # Another slug or another server is another suggestion: both allowed.
    db.add(_dismissal(slug="docker-host"))
    db.add(_dismissal(server_id="srv-2"))
    db.commit()
    dismissals = db.query(MonitorTemplateSuggestionDismissal).all()
    assert len(dismissals) == 3
    assert all(d.dismissed_at is not None for d in dismissals)

    db.add(_dismissal())
    with pytest.raises(IntegrityError):
        db.commit()


# --- cleanup_server -------------------------------------------------------------


def test_cleanup_server_removes_its_host_facts_and_dismissals(db):
    # Neither table has a foreign key to the server (it lives in the server's
    # database), so cleanup_server has to drop the rows itself.
    db.add_all(
        [
            MonitorHostFacts(server_id="srv-1", os="linux", subsystems='["docker"]'),
            MonitorHostFacts(server_id="srv-2", os="windows"),
            _dismissal("srv-1", "linux-base"),
            _dismissal("srv-1", "docker-host"),
            _dismissal("srv-2", "windows-base"),
        ]
    )
    db.commit()

    cleanup_server(db, "srv-1")

    assert [f.server_id for f in db.query(MonitorHostFacts)] == ["srv-2"]
    assert [
        (d.server_id, d.builtin_slug) for d in db.query(MonitorTemplateSuggestionDismissal)
    ] == [("srv-2", "windows-base")]


# --- suggestions: GET /templates/suggestions/{server_id} ------------------------


def _seed(factory, server_id="srv-1", os="linux", subsystems=("docker",)):
    """The shipped standard templates, and the host facts of one server."""
    with factory() as session:
        seed_builtin_templates(session)
        session.add(
            MonitorHostFacts(server_id=server_id, os=os, subsystems=json.dumps(list(subsystems)))
        )
        session.commit()


def _template(factory, slug):
    with factory() as session:
        return session.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == slug).one()


def _slugs(client, server_id="srv-1"):
    r = client.get(f"/templates/suggestions/{server_id}")
    assert r.status_code == 200, r.text
    return [s["slug"] for s in r.json()]


def test_linux_with_docker_suggests_both_templates(client_db):
    client, factory = client_db
    _seed(factory)
    linux, docker = _template(factory, "linux-base"), _template(factory, "docker-host")

    r = client.get("/templates/suggestions/srv-1")

    assert r.status_code == 200
    # The OS first, then the subsystems.
    assert r.json() == [
        {
            "slug": "linux-base",
            "templateId": linux.id,
            "templateName": "Linux Server — Standard",
            "reason": "os:linux",
        },
        {
            "slug": "docker-host",
            "templateId": docker.id,
            "templateName": "Docker Host",
            "reason": "subsystem:docker",
        },
    ]


@pytest.mark.parametrize(
    ("os", "subsystems", "expected"),
    [
        ("windows", (), [("windows-base", "os:windows")]),
        (None, ("zfs",), [("zfs-storage", "subsystem:zfs")]),
        (None, ("proxmox",), [("proxmox-host", "subsystem:proxmox")]),
        # No standard template for macOS, and no OS reported at all.
        ("darwin", (), []),
        (None, (), []),
    ],
)
def test_each_fact_suggests_its_standard_template(client_db, os, subsystems, expected):
    # Seeded from the shipped built-ins: a slug in the rule that ships under another
    # name would never be suggested.
    client, factory = client_db
    _seed(factory, os=os, subsystems=subsystems)

    r = client.get("/templates/suggestions/srv-1")

    assert [(s["slug"], s["reason"]) for s in r.json()] == expected


def test_host_ping_is_never_suggested(client_db):
    # Opt-in: on a host the monitoring service cannot reach by ICMP the ping sits at
    # critical. Suggestions come only from SUGGESTED_SLUGS, so no fact suggests it,
    # and there is nothing to dismiss either.
    client, factory = client_db
    _seed(factory, subsystems=("docker", "zfs", "proxmox"))
    assert _template(factory, "host-ping").name == "Host Ping"

    assert _slugs(client) == ["linux-base", "docker-host", "zfs-storage", "proxmox-host"]
    assert "host-ping" not in SUGGESTED_SLUGS
    r = client.post("/templates/suggestions/srv-1/dismiss", json={"slug": "host-ping"})
    assert r.status_code == 422


def test_suggestion_names_the_template_as_it_is_now(client_db):
    client, factory = client_db
    _seed(factory, subsystems=())
    with factory() as session:
        session.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "linux-base").update(
            {"name": "Linux (ours)"}
        )
        session.commit()

    assert client.get("/templates/suggestions/srv-1").json()[0]["templateName"] == "Linux (ours)"


@pytest.mark.parametrize("source", ["manual", "tag"])
def test_assigned_template_is_not_suggested(client_db, source):
    # Every source counts: a tag binding assigns as much as a manual assignment, and
    # the standard-template sync updates assignments, it creates none of its own.
    client, factory = client_db
    _seed(factory)
    linux_id = _template(factory, "linux-base").id
    with factory() as session:
        session.add(
            MonitorTemplateAssignment(
                id=str(uuid.uuid4()),
                template_id=linux_id,
                server_id="srv-1",
                server_hostname="h",
                server_name="n",
                source=source,
            )
        )
        # Assigned to another server: no reason to leave it out here.
        session.add(
            MonitorTemplateAssignment(
                id=str(uuid.uuid4()),
                template_id=_template(factory, "docker-host").id,
                server_id="srv-2",
                server_hostname="h2",
                server_name="n2",
                source=source,
            )
        )
        session.commit()

    assert _slugs(client) == ["docker-host"]


def test_dismissed_suggestion_is_not_suggested(client_db):
    client, factory = client_db
    _seed(factory)
    with factory() as session:
        session.add(_dismissal("srv-1", "docker-host"))
        session.add(_dismissal("srv-2", "linux-base"))  # another server's decision
        session.commit()

    assert _slugs(client) == ["linux-base"]


def test_deleted_standard_template_is_not_suggested(client_db):
    client, factory = client_db
    _seed(factory)
    assert client.delete(f"/templates/{_template(factory, 'docker-host').id}").status_code == 204

    assert _slugs(client) == ["linux-base"]


def test_server_without_host_facts_gets_no_suggestions(client_db):
    # A new server whose agent has not reported yet, or an agent before R-0421: not
    # an error, there is just nothing to suggest yet.
    client, factory = client_db
    _seed(factory)

    r = client.get("/templates/suggestions/srv-new")

    assert r.status_code == 200
    assert r.json() == []


def test_suggestion_route_is_not_taken_by_a_template_route(client_db):
    # /templates/{template_id}/builtin-update has as many segments as this route:
    # declared first, it would answer for a server named "builtin-update" with its
    # own 404. Through the app's real router, not a direct call.
    client, factory = client_db
    _seed(factory, server_id="builtin-update", subsystems=())

    r = client.get("/templates/suggestions/builtin-update")

    assert r.status_code == 200, r.text
    assert [s["slug"] for s in r.json()] == ["linux-base"]


# --- dismiss: POST /templates/suggestions/{server_id}/dismiss -------------------


def _dismissals(factory):
    with factory() as session:
        return [
            (d.server_id, d.builtin_slug)
            for d in session.query(MonitorTemplateSuggestionDismissal).order_by(
                MonitorTemplateSuggestionDismissal.builtin_slug
            )
        ]


def test_dismiss_hides_the_suggestion_and_is_idempotent(client_db):
    client, factory = client_db
    _seed(factory)

    first = client.post("/templates/suggestions/srv-1/dismiss", json={"slug": "docker-host"})
    second = client.post("/templates/suggestions/srv-1/dismiss", json={"slug": "docker-host"})

    assert (first.status_code, second.status_code) == (204, 204)
    assert _dismissals(factory) == [("srv-1", "docker-host")]
    assert _slugs(client) == ["linux-base"]


@pytest.mark.parametrize("slug", ["no-such-template", "", "Docker-Host"])
def test_dismiss_unknown_slug_is_422(client_db, slug):
    client, factory = client_db
    _seed(factory)

    r = client.post("/templates/suggestions/srv-1/dismiss", json={"slug": slug})

    assert r.status_code == 422
    assert _dismissals(factory) == []


def test_dismiss_on_a_server_without_host_facts_is_404(client_db):
    # Without host facts there was nothing to suggest, so nothing to dismiss: such
    # a row would belong to no server that cleanup_server is ever called for.
    client, factory = client_db
    _seed(factory)
    with factory() as session:
        # Known to the service in other ways, still no facts.
        session.add(MonitorAgentKey(id="k-1", server_id="srv-2", hashed_key="h"))
        session.commit()

    for server_id in ("srv-unknown", "srv-2"):
        r = client.post(f"/templates/suggestions/{server_id}/dismiss", json={"slug": "linux-base"})
        assert r.status_code == 404, server_id
    assert _dismissals(factory) == []
    # The same call for the server with facts goes through.
    r = client.post("/templates/suggestions/srv-1/dismiss", json={"slug": "linux-base"})
    assert r.status_code == 204
    assert _dismissals(factory) == [("srv-1", "linux-base")]


def test_dismiss_takes_server_ids_up_to_uuid_length(client_db):
    client, factory = client_db
    server_id = str(uuid.uuid4())  # what the server's inventory hands out: 36 characters
    _seed(factory, server_id=server_id)

    ok = client.post(f"/templates/suggestions/{server_id}/dismiss", json={"slug": "linux-base"})
    too_long = client.post(
        f"/templates/suggestions/{server_id}x/dismiss", json={"slug": "linux-base"}
    )

    assert ok.status_code == 204
    assert too_long.status_code == 422
    assert client.get(f"/templates/suggestions/{server_id}x").status_code == 422
    assert _dismissals(factory) == [(server_id, "linux-base")]


def test_suggestion_routes_need_the_internal_key(client_db):
    # As their neighbours in routers/templates.py: only the server's proxy calls them.
    from app.core.auth import require_internal
    from app.main import app

    client, factory = client_db
    _seed(factory)
    app.dependency_overrides.pop(require_internal)

    assert client.get("/templates/suggestions/srv-1").status_code == 401
    r = client.post("/templates/suggestions/srv-1/dismiss", json={"slug": "linux-base"})
    assert r.status_code == 401
    assert _dismissals(factory) == []
