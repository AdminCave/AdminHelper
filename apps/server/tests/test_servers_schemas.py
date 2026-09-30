# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure validator logic for the servers/FRP schemas. The server name becomes an
FRP identifier and a path component in generated TOML/ZIP, so its validator is an
injection boundary (TOML breakers, path separators/traversal). The tag validator
trims, length-caps and de-duplicates. Both are pure functions — no DB needed."""

import pytest

from app.modules.frp.schemas import _validate_tags
from app.modules.servers.schemas import _validate_server_name


class TestValidateServerName:
    def test_none_passes_through(self):
        assert _validate_server_name(None) is None

    def test_surrounding_whitespace_stripped(self):
        assert _validate_server_name("  srv1  ") == "srv1"

    @pytest.mark.parametrize("name", ["srv-01", "web_app", "k8s.node", "a"])
    def test_valid_names_unchanged(self, name):
        assert _validate_server_name(name) == name

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_blank_rejected(self, blank):
        with pytest.raises(ValueError):
            _validate_server_name(blank)

    def test_over_100_chars_rejected(self):
        with pytest.raises(ValueError):
            _validate_server_name("x" * 101)

    def test_exactly_100_chars_ok(self):
        name = "x" * 100
        assert _validate_server_name(name) == name

    @pytest.mark.parametrize("name", ["a/b", "/", ".", ".."])
    def test_path_separators_and_traversal_rejected(self, name):
        with pytest.raises(ValueError):
            _validate_server_name(name)

    @pytest.mark.parametrize("name", ['srv"1', "srv\\1", "srv\n1", "srv\r1"])
    def test_toml_breakers_rejected(self, name):
        with pytest.raises(ValueError):
            _validate_server_name(name)

    def test_del_character_rejected(self):
        # The server name reaches the frpc/visitor TOML through the same helper.
        with pytest.raises(ValueError):
            _validate_server_name("srv\x7f1")


class TestValidateTags:
    def test_none_passes_through(self):
        assert _validate_tags(None) is None

    def test_deduplicates_preserving_order(self):
        assert _validate_tags(["b", "a", "b", "a"]) == ["b", "a"]

    def test_strips_then_caps_at_50_chars(self):
        assert _validate_tags(["  " + "x" * 60 + "  "]) == ["x" * 50]

    def test_drops_empty_and_whitespace_only(self):
        assert _validate_tags(["", "  ", "a"]) == ["a"]

    def test_empty_list_yields_empty_list(self):
        assert _validate_tags([]) == []
