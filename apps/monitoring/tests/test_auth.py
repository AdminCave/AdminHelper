# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constant-time, fail-closed key comparison for the monitoring auth
(GHSA-2632). The internal/agent key compare must not be a timing oracle and
must reject when no key is configured."""

from app.core.auth import _key_matches


def test_correct_key_matches():
    assert _key_matches("s3cret-token", "s3cret-token") is True


def test_wrong_key_rejected():
    assert _key_matches("wrong", "s3cret-token") is False


def test_empty_provided_key_rejected():
    assert _key_matches("", "s3cret-token") is False


def test_empty_expected_key_fails_closed():
    # An unconfigured/blank server key must never authenticate anyone,
    # not even a blank provided key.
    assert _key_matches("anything", "") is False
    assert _key_matches("", "") is False


def test_non_ascii_header_does_not_raise():
    # A non-ASCII provided header must compare False, not raise inside
    # compare_digest (which rejects non-ASCII str) -> we compare bytes.
    assert _key_matches("nön-ascii-üîç", "s3cret-token") is False
