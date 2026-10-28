# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for app/core/victoria.py: the InfluxDB line protocol formatting (_esc_tag,
format_line) and the client (buffered writer, query fallback)."""

import logging
import sys
import threading

import httpx
import pytest

import app.core.victoria as victoria_mod
from app.core.victoria import VictoriaClient, _esc_tag, format_line, safe_metric_part


class TestEscTag:
    def test_no_special_chars_unchanged(self):
        assert _esc_tag("plain") == "plain"

    def test_space_escaped(self):
        # The code escapes space as "\ " (backslash-space), not as "\s".
        assert _esc_tag("a b") == "a\\ b"

    def test_comma_escaped(self):
        assert _esc_tag("a,b") == "a\\,b"

    def test_equals_escaped(self):
        assert _esc_tag("a=b") == "a\\=b"

    def test_all_three_in_one(self):
        assert _esc_tag("a b,c=d") == "a\\ b\\,c\\=d"

    def test_multiple_same_char(self):
        assert _esc_tag("a b c") == "a\\ b\\ c"
        assert _esc_tag("a,,b") == "a\\,\\,b"

    def test_empty_string(self):
        assert _esc_tag("") == ""


class TestSafeMetricPart:
    """2.33: the allowlist sanitiser for the device part of a per-disk series name. Its one
    user is the smart_health checker (app/checkers/smart.py); the agent push writes no
    SMART lines."""

    def test_non_allowlisted_chars_collapse_to_underscore(self):
        # A dash is not allowlisted — the old checker's replace("/","_") left it in.
        assert safe_metric_part("sda-1") == "sda_1"

    def test_leading_trailing_separators_stripped(self):
        assert safe_metric_part("/dev/sda") == "dev_sda"
        assert safe_metric_part("/dev/sda/") == "dev_sda"

    def test_empty_or_all_special_falls_back_to_unknown(self):
        # A series name must never end up empty.
        assert safe_metric_part("") == "unknown"
        assert safe_metric_part("///") == "unknown"

    def test_alnum_and_underscore_preserved(self):
        assert safe_metric_part("nvme0n1") == "nvme0n1"


class TestFormatLine:
    def test_int_gets_i_suffix(self):
        # Integer fields get the 'i' suffix in the line protocol.
        assert format_line("m", {"host": "srv"}, 5, 100) == "m,host=srv value=5i 100"

    @pytest.mark.parametrize("edge", [2**63 - 1, -(2**63)])
    def test_int64_edges_keep_i_suffix(self, edge):
        assert format_line("m", {"host": "srv"}, edge, 100) == f"m,host=srv value={edge}i 100"

    @pytest.mark.parametrize(
        ("big", "field"),
        [
            (2**63, "value=9.223372036854776e+18"),
            (-(2**63) - 1, "value=-9.223372036854776e+18"),
            (10**300, "value=1e+300"),
        ],
    )
    def test_int_beyond_int64_is_written_as_float(self, big, field):
        # VictoriaMetrics parses an "i" value as int64 and rejects the whole batch on
        # overflow (HTTP 400), the valid lines of that write too; it stores float64 anyway.
        assert format_line("m", {"host": "srv"}, big, 100) == f"m,host=srv {field} 100"

    @pytest.mark.parametrize("huge", [10**400, -(10**400)])
    def test_int_beyond_float_range_rejected(self, huge):
        # Not even float64 holds it: rejected like inf, not an OverflowError.
        with pytest.raises(ValueError):
            format_line("m", {"host": "srv"}, huge, 100)

    def test_check_lines_skip_an_int_beyond_float_range(self):
        from app.core.victoria import VictoriaClient

        lines = VictoriaClient().build_check_result_lines(
            "c1", "agent_resources", "s1", "chk", "ok", 0, {"x": 10**400, "y": 1}
        )
        assert not [line for line in lines if line.startswith("monitor_x,")]
        assert len([line for line in lines if line.startswith("monitor_y,")]) == 1

    def test_float_no_i_suffix(self):
        assert format_line("m", {"host": "srv"}, 1.5, 100) == "m,host=srv value=1.5 100"

    def test_str_value_rejected(self):
        # A non-numeric value would be written verbatim into the field position
        # (line-protocol injection); it is now rejected.
        with pytest.raises(TypeError):
            format_line("m", {"host": "srv"}, "up", 100)

    def test_bool_value_rejected(self):
        # bool is an int subclass; "value=Truei" is nonsense and a non-metric.
        with pytest.raises(TypeError):
            format_line("m", {"host": "srv"}, True, 100)

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_values_rejected(self, bad):
        # inf/nan written verbatim would poison the whole batch — must be rejected.
        with pytest.raises(ValueError):
            format_line("m", {"host": "srv"}, bad, 100)

    def test_multiple_tags_joined_with_comma(self):
        line = format_line("m", {"a": "1", "b": "2"}, 7, 100)
        assert line == "m,a=1,b=2 value=7i 100"

    def test_empty_tag_value_filtered(self):
        # format_line skips tags with an empty value (if v).
        line = format_line("m", {"a": "1", "b": ""}, 7, 100)
        assert line == "m,a=1 value=7i 100"

    def test_tag_value_is_escaped(self):
        line = format_line("m", {"name": "my check"}, 7, 100)
        assert line == "m,name=my\\ check value=7i 100"


class TestFormatLineEmptyTags:
    def test_all_empty_tags_no_trailing_comma(self):
        # 4.112: an all-empty tag set must not leave a comma before the space (invalid LP).
        assert format_line("m", {}, 5, 100) == "m value=5i 100"
        assert format_line("m", {"a": ""}, 5, 100) == "m value=5i 100"

    def test_nonempty_tags_still_get_the_comma(self):
        assert format_line("m", {"host": "srv"}, 5, 100) == "m,host=srv value=5i 100"


class TestVictoriaClientRobustness:
    def test_query_range_non_json_returns_empty_fallback(self):
        # 4.114: a non-JSON 200 (proxy HTML error page, truncated body) makes resp.json() raise a
        # ValueError; return the empty fallback instead of propagating a 500.
        from app.core.victoria import VictoriaClient

        client = VictoriaClient()

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError("not json")

        class _FakeClient:
            def get(self, *_a, **_k):
                return _FakeResp()

        client._client = _FakeClient()
        assert client.query_range("q", "s", "e", "1m") == {
            "status": "error",
            "data": {"result": []},
        }

    def test_write_retries_a_transient_failure(self, monkeypatch):
        # 4.113: a transient write failure is retried (3 attempts) before giving up, and never
        # raises out of the send method the writer thread runs.
        import app.core.victoria as victoria_mod
        from app.core.victoria import VictoriaClient

        monkeypatch.setattr(victoria_mod, "_sleep", lambda _s: None)  # no real backoff
        client = VictoriaClient()
        attempts = {"n": 0}

        class _FakeClient:
            def post(self, *_a, **_k):
                attempts["n"] += 1
                raise victoria_mod.httpx.ConnectError("boom")

        client._client = _FakeClient()
        client._send(["m,host=srv value=5i 100"])  # must not raise
        assert attempts["n"] == 3


_BASE_URL = "http://192.0.2.10:8428"


def _client_with(handler) -> VictoriaClient:
    """A client whose POSTs go to ``handler`` (an httpx.MockTransport handler)."""
    client = VictoriaClient(_BASE_URL)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def _warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "monitor.victoria" and r.levelno == logging.WARNING
    ]


class TestVictoriaWriter:
    """R-0615, R-0636: write() only queues the lines; a writer thread posts them, retries
    only what can pass on a second try, and close() flushes the buffer on shutdown."""

    def test_write_returns_while_the_post_hangs_and_the_writer_sends_it(self):
        entered, release = threading.Event(), threading.Event()
        posts = []

        def handler(request):
            entered.set()
            release.wait(10)
            posts.append((str(request.url), request.content.decode()))
            return httpx.Response(204)

        client = _client_with(handler)
        lines = ["m,host=a value=1i 100", "m,host=b value=2i 100"]
        caller = threading.Thread(target=client.write, args=(lines,))
        try:
            caller.start()
            caller.join(0.5)
            assert not caller.is_alive(), "write() waited on the POST"
            assert entered.wait(5)
            writer = client._thread
            assert writer.name == "victoria-writer"
            assert writer.daemon
        finally:
            release.set()
            caller.join(10)
        client.close()
        assert posts == [(f"{_BASE_URL}/write", "\n".join(lines))]

    def test_a_write_that_does_not_fit_the_buffer_is_dropped_and_counted(self, monkeypatch, caplog):
        monkeypatch.setattr(victoria_mod, "_MAX_PENDING_LINES", 5)
        clock = [1000.0]
        monkeypatch.setattr(victoria_mod, "_now", lambda: clock[0])
        caplog.set_level(logging.WARNING, logger="monitor.victoria")
        entered, release = threading.Event(), threading.Event()
        bodies = []

        def handler(request):
            entered.set()
            release.wait(10)
            bodies.append(request.content.decode())
            return httpx.Response(204)

        client = _client_with(handler)
        try:
            client.write(["a"])
            assert entered.wait(5)  # "a" hangs in the POST, the buffer is empty
            client.write(["b1", "b2", "b3"])
            client.write(["c1", "c2", "c3"])  # 3 + 3 > 5: dropped as a whole
            client.write(["d1", "d2"])  # 3 + 2 = 5 still fits
            client.write(["e1", "e2"])  # dropped within a minute of the warning: counted only
            clock[0] += 60
            client.write(["f1", "f2"])  # dropped a minute later: reported together with e1, e2
        finally:
            release.set()
        client.close()
        assert bodies == ["a", "b1\nb2\nb3\nd1\nd2"]
        warnings = _warnings(caplog)
        assert len(warnings) == 2, warnings
        assert "dropped 3 lines" in warnings[0]
        assert "dropped 4 lines" in warnings[1]

    def test_lines_dropped_after_a_warning_are_reported_once_the_buffer_is_empty(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(victoria_mod, "_MAX_PENDING_LINES", 2)
        clock = [1000.0]
        monkeypatch.setattr(victoria_mod, "_now", lambda: clock[0])
        caplog.set_level(logging.WARNING, logger="monitor.victoria")
        entered, release = threading.Event(), threading.Event()
        bodies = []

        def handler(request):
            entered.set()
            release.wait(10)
            bodies.append(request.content.decode())
            return httpx.Response(204)

        client = _client_with(handler)
        try:
            client.write(["a"])
            assert entered.wait(5)  # "a" hangs in the POST, the buffer is empty
            client.write(["b1", "b2"])  # the buffer is full
            client.write(["c1"])  # dropped and reported
            clock[0] += 10
            client.write(["d1", "d2", "d3"])  # dropped within the minute: counted only
            assert _warnings(caplog) == [
                "VictoriaMetrics write buffer full (2 lines or 67108864 bytes): "
                "dropped 1 lines since the last report"
            ]
        finally:
            release.set()
        client.close()  # the writer takes b1, b2 off the buffer, which is then empty
        assert bodies == ["a", "b1\nb2"]
        assert _warnings(caplog)[1:] == [
            "VictoriaMetrics write buffer full (2 lines or 67108864 bytes): "
            "dropped 3 lines since the last report"
        ]
        assert client._dropped == 0

    def test_a_write_beyond_the_byte_cap_is_dropped_and_counted(self, monkeypatch, caplog):
        assert victoria_mod._MAX_PENDING_BYTES == 64 * 1024 * 1024
        monkeypatch.setattr(victoria_mod, "_now", lambda: 1000.0)
        caplog.set_level(logging.WARNING, logger="monitor.victoria")
        # One string object queued 100 times: the buffer counts it 100 times, the test holds 1 MiB.
        line = "x" * (1024 * 1024)
        size = sys.getsizeof(line)
        fits = victoria_mod._MAX_PENDING_BYTES // size
        assert fits == 63  # 1 MiB plus the str header, 64 of them exceed 64 MiB
        entered, release = threading.Event(), threading.Event()
        batches = []

        def send(lines):
            # Stands in for the POST, which would join the 63 MiB into one real string.
            batches.append(len(lines))
            entered.set()
            release.wait(10)

        client = VictoriaClient(_BASE_URL)
        client._send = send
        try:
            client.write(["a"])
            assert entered.wait(5)  # "a" hangs in the send, the buffer is empty
            for _ in range(100):
                client.write([line])
            assert len(client._pending) == fits
            assert client._pending_bytes == fits * size
            # The first drop is reported, the later ones within the minute are counted.
            assert client._dropped == 100 - fits - 1
            assert _warnings(caplog) == [
                "VictoriaMetrics write buffer full (100000 lines or 67108864 bytes): "
                "dropped 1 lines since the last report"
            ]
        finally:
            release.set()
        client.close()
        assert batches == [1, fits]

    def test_emptying_the_buffer_frees_its_bytes(self):
        line = "x" * (1024 * 1024)
        fits = victoria_mod._MAX_PENDING_BYTES // sys.getsizeof(line)
        batches = []
        client = VictoriaClient(_BASE_URL)
        client._send = lambda lines: batches.append(len(lines))
        for _ in range(fits):
            client.write([line])
        client.close()
        assert sum(batches) == fits
        assert client._pending_bytes == 0
        client.write([line])  # would not fit had the writer kept the bytes of the sent lines
        client.close()
        assert sum(batches) == fits + 1
        assert client._dropped == 0

    @pytest.mark.parametrize(
        ("outcome", "attempts"),
        [(400, 1), (503, 3), ("connect", 3), ("timeout", 3)],
    )
    def test_only_a_failure_that_can_pass_on_a_retry_is_retried(
        self, monkeypatch, outcome, attempts
    ):
        pauses = []
        monkeypatch.setattr(victoria_mod, "_sleep", pauses.append)
        requests = []

        def handler(request):
            requests.append(request)
            if outcome == "connect":
                raise httpx.ConnectError("connection refused", request=request)
            if outcome == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(outcome, text="cannot process influx line protocol data")

        client = _client_with(handler)
        client.write(["m,host=a value=1i 100"])
        client.close()
        assert len(requests) == attempts
        assert pauses == ([] if attempts == 1 else [0.5, 1.0])

    def test_a_rejected_write_logs_status_lines_and_the_start_of_the_answer(self, caplog):
        caplog.set_level(logging.WARNING, logger="monitor.victoria")
        answer = "cannot process influx line protocol data: incorrect influx line " + "x" * 300
        client = _client_with(lambda request: httpx.Response(400, text=answer))
        client.write(["garbage line without fields", "m,host=a value=1i 100"])
        client.close()
        (warning,) = _warnings(caplog)
        assert "2 lines" in warning
        assert "HTTP 400" in warning
        assert warning.endswith(answer[:200])

    def test_an_unexpected_error_does_not_end_the_writer(self):
        first_done = threading.Event()
        bodies = []

        def handler(request):
            bodies.append(request.content.decode())
            if len(bodies) == 1:
                first_done.set()
                raise RuntimeError("not an httpx error")
            return httpx.Response(204)

        client = _client_with(handler)
        client.write(["a"])
        assert first_done.wait(5)
        client.write(["b"])
        client.close()
        assert bodies == ["a", "b"]

    def test_close_sends_the_buffer_in_batches_and_may_be_called_again(self, monkeypatch):
        monkeypatch.setattr(victoria_mod, "_MAX_BATCH_LINES", 2)
        bodies = []

        def handler(request):
            bodies.append(request.content.decode())
            return httpx.Response(204)

        client = _client_with(handler)
        client.write(["l1", "l2", "l3", "l4", "l5"])
        writer = client._thread
        client.close()
        assert bodies == ["l1\nl2", "l3\nl4", "l5"]
        assert not writer.is_alive()
        client.close()  # a second close is a no-op
        client.write(["l6"])  # and a later write starts a new writer
        client.close()
        assert bodies[-1] == "l6"

    def test_close_returns_after_its_timeout_while_the_post_hangs(self):
        entered, release = threading.Event(), threading.Event()

        def handler(request):
            entered.set()
            release.wait(10)
            return httpx.Response(204)

        client = _client_with(handler)
        client.write(["m,host=a value=1i 100"])
        writer = client._thread
        try:
            assert entered.wait(5)
            client.close(timeout=0.1)
            assert writer.is_alive(), "close() waited for the hanging POST"
        finally:
            release.set()
        writer.join(5)
        assert not writer.is_alive()
