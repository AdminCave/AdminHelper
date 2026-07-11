# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Brute-force limit on /api/auth/login: 5 failed attempts per IP in 60s, counted BEFORE the password
check (so a brute-forcer can't bypass it), and reset on a successful login (4.141). The rate-limit
backend is reset per test by the autouse fixture in conftest (6.78), so no explicit reset here (6.77)."""


def test_login_locks_after_5_failures(test_client, db_session, admin_user):
    for _ in range(5):
        r = test_client.post("/api/auth/login", json={"username": "admin", "password": "falsch"})
        assert r.status_code == 401, r.text
    # The 6th attempt is 429 even with the CORRECT password: the counter increments up front, so the
    # limit can't be bypassed by guessing the right one on the last try.
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 429, r.text


def test_successful_login_resets_the_failure_counter(test_client, db_session, admin_user):
    for _ in range(4):
        r = test_client.post("/api/auth/login", json={"username": "admin", "password": "falsch"})
        assert r.status_code == 401, r.text
    # A success (5th attempt, count == 5, not yet over the limit) resets the counter.
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    # So four more failures do NOT lock out — a legitimate user isn't punished for earlier typos.
    for _ in range(4):
        r = test_client.post("/api/auth/login", json={"username": "admin", "password": "falsch"})
        assert r.status_code == 401, r.text
