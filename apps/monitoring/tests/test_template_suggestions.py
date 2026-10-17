# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template suggestions from the agent's host facts (R-0421): the schema that keeps
what a server's agent last reported about its host and which suggestions an admin
ignored, and the server cleanup that takes both with it."""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MonitorHostFacts, MonitorTemplateSuggestionDismissal
from app.template_sync import cleanup_server


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
