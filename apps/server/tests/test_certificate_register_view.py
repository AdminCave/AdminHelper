# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ca-issuer's view of the server's tables matches the server's models (R-0224).

The ca-issuer consumes enrollment tokens and writes the certificate register through
its own SQLAlchemy Core view (apps/ca-issuer/app/db.py). The two services share no
code, so a column renamed or added on one side would only fail at runtime, at the
first enrollment after an update. The view is read as source, not imported: the
ca-issuer is a separate service with its own venv.
"""

import ast
from pathlib import Path

import pytest

from app.core.database import Base

_ROOT = Path(__file__).resolve().parents[3]
_CA_DB = _ROOT / "apps" / "ca-issuer" / "app" / "db.py"

# The tables the ca-issuer inserts into, as opposed to only reading or updating.
_WRITTEN = ("device_lines", "issued_certificates", "infra_certificates")


def _name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def _view() -> dict[str, set[str]]:
    """Table name -> the column names the ca-issuer's view declares."""
    tables: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(_CA_DB.read_text())):
        if isinstance(node, ast.Call) and _name(node.func) == "Table":
            columns = {
                arg.args[0].value
                for arg in node.args[2:]
                if isinstance(arg, ast.Call) and _name(arg.func) == "Column"
            }
            tables[node.args[0].value] = columns
    return tables


def test_the_view_covers_the_register_and_the_token_tables():
    assert set(_view()) == {
        "enrollment_tokens",
        "revoked_identities",
        "device_lines",
        "issued_certificates",
        "certificate_register_state",
        "infra_certificates",
    }


def test_the_view_names_only_columns_the_server_has():
    for table, columns in _view().items():
        server = set(Base.metadata.tables[table].columns.keys())
        assert columns <= server, f"{table}: {sorted(columns - server)} gibt es im Server nicht"


@pytest.mark.parametrize("table", _WRITTEN)
def test_the_view_carries_every_column_an_insert_needs(table):
    model = Base.metadata.tables[table]
    # Only a server default fills a column the INSERT leaves out: the ORM's Python
    # default (DeviceLine.legacy) never reaches a Core INSERT of the ca-issuer.
    required = {c.name for c in model.columns if not c.nullable and c.server_default is None}
    missing = required - _view()[table]
    assert not missing, f"{table}: ein INSERT des ca-issuer fehlte {sorted(missing)}"
