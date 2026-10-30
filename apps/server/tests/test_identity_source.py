# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The identity headers count only from the gateway (mtls-consistency T2).

The gateway forwards the verified client cert as X-Client-Verify/X-Client-Cert, but
the other services of the compose network reach server:8080 as well. So
get_client_identity takes the headers only when the direct peer is a current address
of the compose name gateway; a miss looks the name up once more out of turn, so that a
recreated gateway with a new address counts at once. No DNS is asked here: a fake
getaddrinfo answers and counts its calls, and the resolver's background thread never
starts, so every lookup is either one out of turn or one the test made with refresh().
"""

import ipaddress
import logging
import socket
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core import config, identity
from app.core import middleware as mw
from app.core.auth import create_access_token
from app.core.database import get_db
from app.core.identity import SCOPE_ACCESS, get_client_identity
from tests.test_mtls_scope import _gateway_headers
from tests.token_claims import claims_for

# Lifts _every_peer_is_the_gateway (conftest): here the real check runs.
pytestmark = pytest.mark.identity_source

GATEWAY = "192.0.2.10"
OTHER = "192.0.2.11"
NEW_GATEWAY = "192.0.2.20"
# The app's own resolver, taken before the autouse fixture swaps in a test one.
_APP_GATEWAY = identity._GATEWAY


class _Dns:
    """A getaddrinfo for the gateway: answers `answer` (addresses, or an OSError to
    raise), first waiting for `gate` if one is set — both as they were when asked —
    and records each name asked."""

    def __init__(self, *addresses: str):
        self.answer: list[str] | OSError = list(addresses)
        self.gate: threading.Event | None = None
        self.asked: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.asked)

    def __call__(self, host, port, *args, **kwargs):
        self.asked.append(host)
        answer, gate = self.answer, self.gate
        if gate is not None:
            gate.wait(timeout=10)
        if isinstance(answer, OSError):
            raise answer
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (a, 0)) for a in answer
        ]


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    monkeypatch.setattr(mw._NameResolver, "_start", lambda self: None)
    fake = _Dns(GATEWAY)
    resolver = mw._NameResolver(
        list(identity._GATEWAY_NAMES), fake, label="mTLS identity", thread_name="gateway-names"
    )
    monkeypatch.setattr(identity, "_GATEWAY", resolver)
    monkeypatch.setattr(identity, "_ignored_logged", {})
    return fake


def _req(peer: str | None, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }
    if peer is not None:
        scope["client"] = (peer, 50000)
    return Request(scope)


def _ignored(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and "does not come from the gateway" in r.getMessage()
    ]


def test_headers_from_the_gateway_count(dns):
    identity._GATEWAY.refresh()
    ident = get_client_identity(_req(GATEWAY, _gateway_headers(cn="user-01")))
    assert ident.verified is True
    assert (ident.cn, ident.scope) == ("user-01", SCOPE_ACCESS)
    # As an absolute name, so no search domain is tried; the cached address answers, no lookup
    # out of turn.
    assert dns.asked == ["gateway."]


def test_the_first_request_before_any_lookup_counts(dns):
    # Right after the start the cache is empty; the lookup out of turn fills it.
    assert get_client_identity(_req(GATEWAY, _gateway_headers())).verified is True
    assert dns.calls == 1


def test_headers_from_another_peer_are_ignored_with_one_warning_a_minute(dns, caplog):
    identity._GATEWAY.refresh()
    with caplog.at_level(logging.WARNING, logger="adminhelper.identity"):
        assert get_client_identity(_req(OTHER, _gateway_headers())).verified is False
        assert len(_ignored(caplog)) == 1
        assert OTHER in _ignored(caplog)[0]

        assert get_client_identity(_req(OTHER, _gateway_headers())).verified is False
        assert len(_ignored(caplog)) == 1

        assert get_client_identity(_req("192.0.2.12", _gateway_headers())).verified is False
        assert len(_ignored(caplog)) == 2  # another peer has a minute of its own

        identity._ignored_logged[OTHER] -= 60  # a minute later
        assert get_client_identity(_req(OTHER, _gateway_headers())).verified is False
        assert len(_ignored(caplog)) == 3


def test_headers_without_a_peer_are_ignored(dns, caplog):
    identity._GATEWAY.refresh()
    with caplog.at_level(logging.WARNING, logger="adminhelper.identity"):
        assert get_client_identity(_req(None, _gateway_headers())).verified is False
    assert [m for m in _ignored(caplog) if "an unknown peer" in m]
    assert dns.calls == 1  # no peer, nothing to look up


def test_a_new_gateway_address_counts_at_once(dns):
    identity._GATEWAY.refresh()  # the cache holds 192.0.2.10
    dns.answer = [NEW_GATEWAY]  # the gateway was recreated
    assert get_client_identity(_req(NEW_GATEWAY, _gateway_headers())).verified is True
    assert dns.calls == 2  # exactly one lookup out of turn
    # The old address went with it: it may belong to another container by now.
    assert get_client_identity(_req(GATEWAY, _gateway_headers())).verified is False

    identity._GATEWAY._urgent_at -= 1  # a second later
    dns.answer = ["192.0.2.21"]  # recreated once more
    assert get_client_identity(_req("192.0.2.21", _gateway_headers())).verified is True
    assert dns.calls == 3  # the next lookup out of turn, not only the first one


def test_a_warning_clears_the_entries_older_than_a_minute(dns, caplog):
    identity._GATEWAY.refresh()
    with caplog.at_level(logging.WARNING, logger="adminhelper.identity"):
        assert get_client_identity(_req(OTHER, _gateway_headers())).verified is False
        assert get_client_identity(_req("192.0.2.12", _gateway_headers())).verified is False
        identity._ignored_logged[OTHER] -= 60  # a minute later
        assert get_client_identity(_req("192.0.2.13", _gateway_headers())).verified is False
        assert len(_ignored(caplog)) == 3
    # Peers that come and go leave no entry behind once their minute is over.
    assert set(identity._ignored_logged) == {"192.0.2.12", "192.0.2.13"}


def test_misses_in_the_same_second_share_one_lookup(dns):
    identity._GATEWAY.refresh()
    for _ in range(2):
        assert get_client_identity(_req(OTHER, _gateway_headers())).verified is False
    assert dns.calls == 2  # the refresh() above, and one lookup out of turn


def test_misses_during_a_running_lookup_wait_for_it(dns):
    # After an update several clients come in at once from the new address: none
    # starts a lookup of its own, and all of them count once the running one answers.
    identity._GATEWAY.refresh()
    dns.answer = [NEW_GATEWAY]
    dns.gate = threading.Event()
    results: list[bool] = []

    def call():
        results.append(get_client_identity(_req(NEW_GATEWAY, _gateway_headers())).verified)

    threads = [threading.Thread(target=call) for _ in range(3)]
    try:
        threads[0].start()
        deadline = time.monotonic() + 5
        while dns.calls < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        for t in threads[1:]:
            t.start()
        time.sleep(0.05)
    finally:
        dns.gate.set()
        for t in threads:
            t.join(timeout=5)
    assert results == [True, True, True]
    assert dns.calls == 2


def test_a_late_round_does_not_publish_over_a_newer_one(dns):
    # The thread's round asked before the gateway was recreated and answers late; the
    # lookup out of turn that a request starts meanwhile has the last word.
    gate = dns.gate = threading.Event()
    late = threading.Thread(target=identity._GATEWAY.refresh)
    results: list[bool] = []

    def call():
        results.append(get_client_identity(_req(NEW_GATEWAY, _gateway_headers())).verified)

    request = threading.Thread(target=call)
    try:
        late.start()
        deadline = time.monotonic() + 5
        while dns.calls < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        dns.answer, dns.gate = [NEW_GATEWAY], None
        request.start()
        time.sleep(0.05)
    finally:
        gate.set()
        late.join(timeout=5)
        request.join(timeout=5)
    assert results == [True]
    assert identity._GATEWAY.networks() == [ipaddress.ip_network(NEW_GATEWAY)]


def test_a_failing_lookup_leaves_the_request_unverified(dns, caplog):
    dns.answer = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    with caplog.at_level(logging.WARNING):
        assert get_client_identity(_req(GATEWAY, _gateway_headers())).verified is False
    assert [r for r in caplog.records if r.getMessage().startswith("mTLS identity: cannot resolve")]


def test_a_slow_lookup_holds_the_request_at_most_a_second(dns):
    # The request reads its identity twice, as the scope guard and the binding to the
    # user do; it waits for the lookup once, not once per read.
    dns.gate = threading.Event()
    request = _req(GATEWAY, _gateway_headers())
    try:
        start = time.monotonic()
        for _ in range(2):
            assert get_client_identity(request).verified is False
        waited = time.monotonic() - start
    finally:
        dns.gate.set()
    assert 0.9 <= waited < 1.5


def test_one_request_keeps_its_first_answer(dns):
    identity._GATEWAY.refresh()
    request = _req(GATEWAY, _gateway_headers())
    assert get_client_identity(request).verified is True
    dns.answer = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    identity._GATEWAY.refresh()  # the next round fails and drops the address
    assert get_client_identity(request).verified is True
    # A new request sees the change.
    assert get_client_identity(_req(GATEWAY, _gateway_headers())).verified is False


def test_a_request_without_the_headers_asks_no_lookup(dns, caplog):
    cert = _gateway_headers()["X-Client-Cert"]
    with caplog.at_level(logging.WARNING, logger="adminhelper.identity"):
        for headers in (
            {},
            {"X-Client-Verify": "NONE"},
            {"X-Client-Verify": "FAILED:certificate has expired", "X-Client-Cert": cert},
            {"X-Client-Cert": cert},
        ):
            assert get_client_identity(_req(OTHER, headers)).verified is False
    assert dns.calls == 0
    assert _ignored(caplog) == []


def _get_servers(db_session, peer: str, username: str, cn: str):
    """GET /api/servers from `peer` with the user's token and an access cert of `cn`."""
    from app.main import app

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        return TestClient(app, client=(peer, 50000)).get(
            "/api/servers",
            headers={
                "Authorization": f"Bearer {create_access_token(claims_for(username))}",
                **_gateway_headers(cn=cn, ou=SCOPE_ACCESS),
            },
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(("peer", "expected"), [(OTHER, 403), (GATEWAY, 200)])
def test_the_servers_route_takes_the_certificate_only_from_the_gateway(
    db_session, admin_user, monkeypatch, peer, expected
):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    identity._GATEWAY.refresh()
    resp = _get_servers(db_session, peer, admin_user.username, cn=admin_user.username)
    assert resp.status_code == expected, resp.text
    if expected == 403:
        # The scope guard found no certificate, not one of another user.
        assert resp.json()["detail"] == "Kein gültiges Client-Zertifikat mit passendem Scope"


class _Flipping:
    """A resolver whose answer turns after the first question, as when a round fails
    or another request refreshes it while this one is being served."""

    def __init__(self):
        self.answers: list[bool] = []

    def has_address(self, address: str, wait: float) -> bool:
        self.answers.append(not self.answers)  # True first, then False
        return self.answers[-1]


def test_the_binding_to_the_user_sees_the_answer_of_the_scope_guard(
    db_session, admin_user, monkeypatch
):
    # The scope guard reads the identity first, the binding to the user after it. Were
    # the second read to see no cert, a cert of another user would pass with an admin
    # token.
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    flipping = _Flipping()
    monkeypatch.setattr(identity, "_GATEWAY", flipping)
    resp = _get_servers(db_session, GATEWAY, admin_user.username, cn="intruder")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == identity.CERT_USER_MISMATCH
    assert flipping.answers == [True]


def test_the_app_starts_the_name_lookups_before_the_first_request(test_client, monkeypatch):
    import httpx

    import app.core.events as events
    import app.main as m
    from app.modules.monitoring_proxy import router as proxy
    from app.modules.notifications import stream_hub

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda *a, **k: None)
    monkeypatch.setattr(stream_hub, "start", _noop)
    monkeypatch.setattr(stream_hub, "stop", _noop)
    # The shutdown closes the proxy client; monkeypatch puts the one of the other tests back.
    monkeypatch.setattr(proxy, "_client", httpx.AsyncClient(timeout=30))
    started = []
    monkeypatch.setattr(mw._NameResolver, "_start", lambda self: started.append(self))
    monkeypatch.setattr(mw, "_PROXY_NAMES", mw._NameResolver(["proxy"], _Dns(OTHER)))
    with test_client:
        pass
    assert started == [mw._PROXY_NAMES, identity._GATEWAY]


def test_gateway_names_are_looked_up_again_sooner_than_proxy_names(monkeypatch):
    # R-0959: an old gateway address is trusted with client certificates, so the gateway's
    # names come back after 5 s, the proxies' after 30 s.
    monkeypatch.setattr(_APP_GATEWAY, "_getaddrinfo", _Dns(GATEWAY))
    monkeypatch.setattr(_APP_GATEWAY, "_networks", [])
    assert _APP_GATEWAY.refresh() == 5
    assert mw._NameResolver(["proxy"], _Dns(OTHER)).refresh() == 30
