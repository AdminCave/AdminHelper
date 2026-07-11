# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""save_connections upsert+delete sync (6.145). It is reachable from hook scripts — admin-written code
that relies on the semantics — and replaced the earlier DELETE-ALL+INSERT-ALL. A regression back to
'wipe everything' (or losing the delete-of-missing) would go unnoticed without this."""

from sqlalchemy.orm import sessionmaker

from app.core import database
from app.modules.connections import storage
from app.modules.connections.models import Connection


def _bind_sessionlocal(db_session, monkeypatch):
    # save_connections opens its own SessionLocal; bind a fresh one to the test connection so its
    # commit lands in the test's transaction (same pattern as test_hooks).
    monkeypatch.setattr(
        database, "SessionLocal", sessionmaker(bind=db_session.connection(), autoflush=False)
    )


def test_save_connections_updates_inserts_and_deletes(db_session, monkeypatch):
    _bind_sessionlocal(db_session, monkeypatch)
    db_session.add(Connection(id="keep", name="old-name", kind="ssh"))
    db_session.add(Connection(id="gone", name="to-delete", kind="ssh"))
    db_session.commit()

    # Sync: update "keep", drop "gone" (absent from the list), insert "new".
    storage.save_connections(
        [
            {"id": "keep", "name": "new-name", "kind": "ssh"},
            {"id": "new", "name": "fresh", "kind": "rdp"},
        ]
    )

    rows = {c.id: c for c in db_session.query(Connection).all()}
    assert set(rows) == {"keep", "new"}, "gone must be deleted, new inserted"
    assert rows["keep"].name == "new-name", "existing id is updated in place, not recreated"
    assert rows["new"].kind == "rdp"


def test_save_connections_empty_list_clears_all(db_session, monkeypatch):
    # The delete-of-missing branch taken to its extreme: an empty list removes every row.
    _bind_sessionlocal(db_session, monkeypatch)
    db_session.add(Connection(id="a", name="a", kind="ssh"))
    db_session.commit()

    storage.save_connections([])

    assert db_session.query(Connection).count() == 0
