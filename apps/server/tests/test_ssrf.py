# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DNS deadline of the server's SSRF guard (harness 8a, T5).

The address classification itself is covered by the monitoring suite
(apps/monitoring/tests/test_ssrf.py) and pinned to this copy by
test_ssrf_parity.py — repeating the range table here would be the second copy
this stage exists to prevent. What is specific to this file is the mechanism
that was missing: a hung resolver must not park the caller for the OS default.
"""

import time

import app.core.ssrf as ssrf_mod


def test_dns_resolution_times_out_and_fails_closed(monkeypatch):
    # The hook worker reaches this guard from the unauthenticated public webhook,
    # so the target host is attacker-chosen: pointed at a dead nameserver, an
    # uncapped getaddrinfo parks the worker for ~30 s per request (4.111).
    def _slow_getaddrinfo(*_a, **_k):
        time.sleep(2)  # simulate a hung resolver
        return []

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _slow_getaddrinfo)
    monkeypatch.setattr(ssrf_mod, "_DNS_TIMEOUT_S", 0.1)

    start = time.monotonic()
    assert ssrf_mod.is_private_url("http://slow-dns.example") is True
    # Fail-closed is only half the guarantee; returning promptly is the other.
    assert time.monotonic() - start < 1.0
