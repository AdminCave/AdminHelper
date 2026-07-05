# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""TcpChecker SSRF guard (3.25): a TCP check to a private/reserved target must be
refused before the connect, so it can't be used to port-scan the internal network.
The successful-connect path is left out — it needs the network."""

import pytest

from app.checkers.tcp import TcpChecker


@pytest.mark.parametrize(
    "target",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "0.0.0.0"],
)
def test_private_targets_refused_ssrf(target):
    status, msg, metrics = TcpChecker().run({"target": target, "port": 8428})
    assert status == "unknown"
    assert "SSRF" in msg
    assert metrics is None


def test_missing_target_or_port_is_unknown():
    assert TcpChecker().run({"target": "", "port": 80})[0] == "unknown"
    assert TcpChecker().run({"target": "example.com", "port": None})[0] == "unknown"
