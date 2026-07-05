# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PingChecker — RTT parsing + target hardening. The target is passed to a
subprocess argv, so the _VALID_TARGET allowlist is a command-injection boundary:
anything but a bare hostname/IP must be refused BEFORE the subprocess runs. The
subprocess (valid-target) path is left out — it needs the network."""

import pytest

from app.checkers.ping import PingChecker, _parse_rtt


class TestParseRtt:
    @pytest.mark.parametrize(
        "out,want",
        [
            ("64 bytes from h: icmp_seq=1 ttl=64 time=0.043 ms", 0.043),
            ("rtt min/avg/max = 1/2/3 ms\n... time=12 ms", 12.0),
            ("time<1.5 ms", 1.5),  # the '<' form some pings emit
        ],
    )
    def test_extracts_first_rtt(self, out, want):
        assert _parse_rtt(out) == want

    @pytest.mark.parametrize("out", ["", "no timing here", "latency: none"])
    def test_returns_none_without_a_match(self, out):
        assert _parse_rtt(out) is None


class TestPingTargetHardening:
    def _status(self, target):
        # run() returns (status, message, metrics); a refused target never
        # reaches the subprocess and comes back "unknown".
        return PingChecker().run({"target": target, "timeout": 1})[0]

    def test_empty_target_is_unknown(self):
        assert self._status("") == "unknown"

    @pytest.mark.parametrize(
        "evil",
        [
            "x; rm -rf /",  # shell metacharacters
            "1.1.1.1/32",  # CIDR slash
            "host name",  # space
            "$(whoami)",  # command substitution
            "a" * 254,  # over the 253-char hostname limit
        ],
    )
    def test_invalid_targets_refused_before_subprocess(self, evil):
        assert self._status(evil) == "unknown"

    @pytest.mark.parametrize("target", ["127.0.0.1", "10.0.0.1", "169.254.169.254"])
    def test_private_targets_refused_ssrf(self, target):
        # 3.25: a valid-format but private/reserved target is blocked before ping.
        status, msg, _ = PingChecker().run({"target": target})
        assert status == "unknown"
        assert "SSRF" in msg
