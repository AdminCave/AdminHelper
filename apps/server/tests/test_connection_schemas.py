# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Pydantic schemas: ConnectionCreate, ConnectionUpdate."""

import pytest
from pydantic import ValidationError

from app.modules.connections.schemas import ConnectionCreate, ConnectionUpdate


class TestConnectionCreate:
    def test_minimal_valid(self):
        c = ConnectionCreate(name="Test", kind="ssh")
        assert c.name == "Test"
        assert c.kind == "ssh"
        assert c.port is None
        assert c.tags == []

    def test_full_valid(self):
        c = ConnectionCreate(
            name="Webserver",
            kind="web",
            host="example.com",
            port=443,
            url="https://example.com",
            tags=["prod", "web"],
        )
        assert c.port == 443
        assert c.tags == ["prod", "web"]

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(kind="ssh")

    def test_kind_required(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="Test")

    def test_blank_name_rejected(self):
        with pytest.raises(ValidationError, match="Name darf nicht leer sein"):
            ConnectionCreate(name="   ", kind="ssh")

    def test_name_stripped(self):
        c = ConnectionCreate(name="  Trimmed  ", kind="ssh")
        assert c.name == "Trimmed"

    def test_port_min_boundary(self):
        c = ConnectionCreate(name="Test", kind="ssh", port=1)
        assert c.port == 1

    def test_port_max_boundary(self):
        c = ConnectionCreate(name="Test", kind="ssh", port=65535)
        assert c.port == 65535

    def test_port_zero_rejected(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="Test", kind="ssh", port=0)

    def test_port_too_high_rejected(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="Test", kind="ssh", port=65536)

    def test_port_negative_rejected(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="Test", kind="ssh", port=-1)

    def test_extra_fields_allowed(self):
        c = ConnectionCreate(name="Test", kind="ssh", customField="value")
        assert c.model_dump()["customField"] == "value"


class TestConnectionUpdate:
    def test_all_optional(self):
        u = ConnectionUpdate()
        assert u.name is None
        assert u.kind is None
        assert u.port is None

    def test_partial_update(self):
        u = ConnectionUpdate(name="New Name")
        data = u.model_dump(exclude_unset=True)
        assert data == {"name": "New Name"}

    def test_blank_name_rejected(self):
        with pytest.raises(ValidationError):
            ConnectionUpdate(name="")

    def test_port_validation(self):
        with pytest.raises(ValidationError):
            ConnectionUpdate(port=99999)

    def test_none_name_allowed(self):
        """name=None means 'dont update', not blank."""
        u = ConnectionUpdate(name=None)
        assert u.name is None
