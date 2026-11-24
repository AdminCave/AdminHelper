# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shared-secret comparison of both services' service-to-service gates. What a mismatch
answers (status code, message) stays each service's own."""

import secrets


def key_matches(provided: str | None, expected: str) -> bool:
    """Constant-time key comparison. Fails closed when no key is configured (an empty
    expected key must never authenticate), and a None provided value is False.

    Compares BYTES: secrets.compare_digest raises TypeError on str arguments holding
    non-ASCII, and header values are latin-1 decoded — so a single byte above 0x7F would
    turn the gate into an unhandled 500 instead of a refusal."""
    return bool(expected) and secrets.compare_digest((provided or "").encode(), expected.encode())
