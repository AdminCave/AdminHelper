# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1080: the outbox delivers ntfy, Telegram and webhook through the SSRF guard
(the networks of NOTIFY_PRIVATE_TARGETS open), without redirects, and names no
secret in last_error or the log."""

import base64
import ipaddress
import json
import logging
import socket
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from email.header import decode_header

import httpx
import pytest

import app.core.config as app_config
import app.core.ssrf as ssrf_mod
from app.core.ssrf import UrlVerdict
from app.modules.notifications import outbox as outbox_mod
from app.modules.notifications import sender as sender_mod
from app.modules.notifications.models import NotificationOutbox, NotificationSettings
from app.modules.notifications.outbox import drain_outbox
from app.modules.notifications.sender import (
    BlockedTarget,
    DeliveryFailed,
    send_ntfy,
    send_telegram,
    send_webhook,
)
from app.modules.notifications.service import ingest_event

from .test_notifications import _event, _server, _sub, _user
from .test_outbox import _notif, _outbox

TOKEN = "123456:secret-bot-token"
NTFY_URL = "https://ntfy.example/alerts?auth=c2VjcmV0LWF1dGg"
HOOK_URL = "https://hooks.example/in/secret-path"


# A public address (as in test_ssrf): the documentation ranges count as private.
class _Wire:
    """The requests the pinned client would have sent, answered by `respond`."""

    def __init__(self, monkeypatch, address="93.184.216.34"):
        self.requests: list[httpx.Request] = []
        self.respond = lambda request: httpx.Response(200)
        self.resolve(monkeypatch, address)
        monkeypatch.setattr(sender_mod, "pinned_client", self._client)

    def resolve(self, monkeypatch, address):
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        answer = [(family, socket.SOCK_STREAM, 6, "", (address, 0))]
        monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", lambda *_a, **_k: answer)

    def _client(self, url, target):
        assert target.addresses, "a client only for a checked target"

        def handler(request):
            self.requests.append(request)
            return self.respond(request)

        return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(app_config, "NOTIFY_PRIVATE_TARGETS", ())
    return _Wire(monkeypatch)


# --- format per channel --------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "priority"), [("critical", "5"), ("warning", "4"), ("info", "3"), ("ok", "2")]
)
def test_ntfy_posts_the_text_with_title_and_priority(wire, level, priority):
    send_ntfy(NTFY_URL, "CPU critical on web01", "Load 12.5", level)
    [request] = wire.requests
    assert request.method == "POST"
    assert str(request.url) == NTFY_URL
    assert request.content == b"Load 12.5"
    assert request.headers["X-Title"] == "CPU critical on web01"
    assert request.headers["X-Priority"] == priority


def test_ntfy_encodes_a_non_ascii_title_by_rfc_2047(wire):
    send_ntfy(NTFY_URL, "Prüfung fehlgeschlagen ✓", "x", "info")
    header = wire.requests[0].headers["X-Title"]
    assert header.startswith("=?UTF-8?B?")
    [(raw, charset)] = decode_header(header)
    assert raw.decode(charset) == "Prüfung fehlgeschlagen ✓"


def test_ntfy_title_stays_one_line(wire):
    send_ntfy(NTFY_URL, "a\nb\rc", "x", "info")
    assert wire.requests[0].headers["X-Title"] == "a b c"


def test_ntfy_cuts_the_body_to_4096_bytes_at_a_character(wire):
    send_ntfy(NTFY_URL, "t", "ä" * 3000, "info")  # 6000 bytes
    body = wire.requests[0].content
    assert len(body) <= 4096
    text = body.decode("utf-8")  # still valid UTF-8, so ntfy keeps it a message
    assert text.endswith("…") and set(text[:-1]) == {"ä"}


def test_telegram_sends_title_and_text_as_plain_text(wire):
    send_telegram("4711", "CPU critical", "Load 12.5")
    send_telegram("4711", "CPU critical", "CPU critical")  # a ping without a text of its own
    request, title_only = wire.requests
    assert json.loads(title_only.content)["text"] == "CPU critical"
    assert str(request.url) == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = json.loads(request.content)
    assert payload == {"chat_id": "4711", "text": "CPU critical\n\nLoad 12.5"}


def test_telegram_cuts_the_text_to_4096_utf16_units(wire):
    send_telegram("4711", "t", "😀" * 3000)  # two UTF-16 units each
    text = json.loads(wire.requests[0].content)["text"]
    assert len(text.encode("utf-16-le")) // 2 <= 4096
    assert text.endswith("…") and text.startswith("t\n\n😀")


def test_telegram_without_token_sends_nothing(wire, monkeypatch):
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(DeliveryFailed):
        send_telegram("4711", "t", "b")
    assert wire.requests == []


def test_webhook_posts_the_ping_as_json(wire):
    send_webhook(HOOK_URL, "CPU critical", "Load 12.5", "ok", "monitoring")
    [request] = wire.requests
    assert request.headers["Content-Type"] == "application/json"
    payload = json.loads(request.content)
    sent_at = payload.pop("sent_at")
    assert payload == {
        "title": "CPU critical",
        "body": "Load 12.5",
        "severity": "ok",
        "category": "monitoring",
    }
    assert abs(datetime.fromisoformat(sent_at) - datetime.now(timezone.utc)) < timedelta(minutes=1)


# --- SSRF guard, redirects, errors ----------------------------------------------------


@pytest.mark.parametrize("send", ["ntfy", "webhook"])
def test_a_private_target_is_blocked_without_a_listed_network(wire, monkeypatch, send):
    wire.resolve(monkeypatch, "192.168.1.20")
    with pytest.raises(BlockedTarget):
        _send(send)
    assert wire.requests == []
    monkeypatch.setattr(
        app_config, "NOTIFY_PRIVATE_TARGETS", (ipaddress.ip_network("192.168.1.0/24"),)
    )
    _send(send)
    assert len(wire.requests) == 1


def test_loopback_stays_blocked_with_a_listed_network(wire, monkeypatch):
    wire.resolve(monkeypatch, "127.0.0.1")
    monkeypatch.setattr(app_config, "NOTIFY_PRIVATE_TARGETS", (ipaddress.ip_network("0.0.0.0/0"),))
    with pytest.raises(BlockedTarget):
        _send("webhook")
    assert wire.requests == []


def test_an_unresolved_host_is_a_failed_attempt_not_a_block(wire, monkeypatch):
    def fail(*_a, **_k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", fail)
    with pytest.raises(DeliveryFailed) as caught:
        _send("ntfy")
    assert not isinstance(caught.value, BlockedTarget)


def test_a_redirect_is_not_followed(wire):
    wire.respond = lambda request: httpx.Response(302, headers={"Location": "http://127.0.0.1/"})
    with pytest.raises(DeliveryFailed, match="HTTP 302"):
        _send("webhook")
    assert len(wire.requests) == 1


def test_a_network_error_names_no_secret(wire):
    def boom(request):
        raise httpx.ConnectError(f"connect failed for {request.url}", request=request)

    wire.respond = boom
    for channel in ("ntfy", "telegram", "webhook"):
        with pytest.raises(DeliveryFailed) as caught:
            _send(channel)
        assert str(caught.value) == f"{channel}: ConnectError"
        # Neither cause nor context: a logged traceback would show the URL.
        assert caught.value.__cause__ is None and caught.value.__context__ is None


def _send(channel):
    if channel == "ntfy":
        send_ntfy(NTFY_URL, "t", "b", "info")
    elif channel == "telegram":
        send_telegram("4711", "t", "b")
    else:
        send_webhook(HOOK_URL, "t", "b", "info", "monitoring")


# --- a target that never ends its answer --------------------------------------------


class _Peer:
    """A real HTTP peer on loopback: /drip drips its headers, /flood sends an endless
    body, /ok answers 204. The guard and the pin are bypassed (loopback stays blocked
    there), the client is a plain one."""

    def __init__(self):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.closed = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            path = conn.recv(65536).split(b" ", 2)[1]
            if path == b"/ok":
                conn.sendall(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n")
                return
            if path == b"/drip":
                conn.sendall(b"HTTP/1.1 200 OK\r\n")
                while True:
                    conn.sendall(b"X")
                    time.sleep(0.05)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n")
            chunk = b"A" * 65536
            while True:
                conn.sendall(chunk)
        except OSError:
            self.closed.set()
        finally:
            conn.close()


@pytest.fixture
def peer(monkeypatch):
    allowed = types.SimpleNamespace(verdict=UrlVerdict.ALLOWED, addresses=("127.0.0.1",))
    monkeypatch.setattr(sender_mod, "check_target", lambda *_a, **_k: allowed)
    monkeypatch.setattr(sender_mod, "pinned_client", lambda *_a, **_k: httpx.Client())
    monkeypatch.setattr(sender_mod, "_SEND_DEADLINE", 1)
    server = _Peer()
    yield server
    server.sock.close()


def test_a_dripping_answer_ends_at_the_deadline(peer):
    started = time.monotonic()
    with pytest.raises(DeliveryFailed, match="webhook: no answer within 1 s"):
        send_webhook(f"{peer.url}/drip", "t", "b", "info", "monitoring")
    assert time.monotonic() - started < 3
    assert peer.closed.wait(3), "the connection of the missed send is closed"


def test_an_endless_body_is_not_read(peer):
    started = time.monotonic()
    send_ntfy(f"{peer.url}/flood", "t", "b", "info")  # the status alone: 200
    assert time.monotonic() - started < 1


def test_too_many_hanging_sends_fail_at_once(peer, monkeypatch):
    full = threading.BoundedSemaphore(1)
    full.acquire()
    monkeypatch.setattr(sender_mod, "_SEND_INFLIGHT", full)
    with pytest.raises(DeliveryFailed, match="too many sends"):
        send_webhook(f"{peer.url}/ok", "t", "b", "info", "monitoring")


def test_a_hanging_target_does_not_hold_up_the_drain(db_session, peer):
    user = _user(db_session, "alice")
    notif = _notif(db_session, user)
    hanging = _outbox(db_session, notif, user, channel="webhook", address=f"{peer.url}/drip")
    other = _outbox(db_session, notif, user, channel="ntfy", address=f"{peer.url}/ok")
    assert drain_outbox(db_session) == (1, 0)
    db_session.refresh(hanging)
    db_session.refresh(other)
    assert (hanging.status, hanging.attempts) == ("pending", 1)
    assert hanging.last_error == "webhook: no answer within 1 s"
    assert other.status == "sent"
    deadline = time.monotonic() + 3  # the closed client ends the hung thread soon after
    while sender_mod._SEND_INFLIGHT._value < sender_mod._SEND_MAX_INFLIGHT:
        assert time.monotonic() < deadline, "the permit of the hung send comes back"
        time.sleep(0.05)


# --- outbox drain ---------------------------------------------------------------------


def test_drain_delivers_each_channel_with_the_level_of_its_ping(db_session, wire):
    user = _user(db_session, "alice")
    notif = _notif(db_session, user)  # a critical bell row
    _outbox(db_session, notif, user, channel="ntfy", address=NTFY_URL, severity="ok")
    _outbox(db_session, notif, user, channel="ntfy", address=NTFY_URL)  # from before R-1080
    _outbox(db_session, notif, user, channel="telegram", address="4711")
    _outbox(db_session, notif, user, channel="webhook", address=HOOK_URL, severity="warning")
    assert drain_outbox(db_session) == (4, 0)
    ntfy_ok, ntfy_old, telegram, webhook = wire.requests
    assert ntfy_ok.headers["X-Priority"] == "2"
    assert ntfy_old.headers["X-Priority"] == "5"  # the notification's severity
    assert json.loads(telegram.content)["chat_id"] == "4711"
    payload = json.loads(webhook.content)
    assert (payload["severity"], payload["category"]) == ("warning", "monitoring")
    assert {e.status for e in db_session.query(NotificationOutbox)} == {"sent"}


def test_drain_leaves_telegram_waiting_without_a_token(db_session, wire, monkeypatch):
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
    user = _user(db_session, "alice")
    entry = _outbox(db_session, _notif(db_session, user), user, channel="telegram", address="4711")
    assert drain_outbox(db_session) == (0, 0)
    db_session.refresh(entry)
    assert (entry.status, entry.attempts) == ("pending", 0)
    assert wire.requests == []


def test_drain_fails_a_blocked_target_at_once(db_session, wire, monkeypatch):
    wire.resolve(monkeypatch, "10.0.0.5")
    user = _user(db_session, "alice")
    entry = _outbox(db_session, _notif(db_session, user), user, channel="webhook", address=HOOK_URL)
    assert drain_outbox(db_session) == (0, 1)
    db_session.refresh(entry)
    assert (entry.status, entry.attempts) == ("failed", 1)
    assert entry.last_error == "webhook: target address not allowed (private)"


def test_drain_retries_a_server_error_with_backoff(db_session, wire):
    wire.respond = lambda request: httpx.Response(503)
    user = _user(db_session, "alice")
    entry = _outbox(db_session, _notif(db_session, user), user, channel="ntfy", address=NTFY_URL)
    assert drain_outbox(db_session) == (0, 0)
    db_session.refresh(entry)
    assert (entry.status, entry.attempts, entry.last_error) == ("pending", 1, "ntfy: HTTP 503")
    assert entry.next_attempt_at is not None


def test_drain_names_no_secret_in_last_error_or_log(db_session, wire, monkeypatch, caplog):
    def boom(request):
        raise httpx.ConnectError(f"connect failed for {request.url}", request=request)

    wire.respond = boom
    monkeypatch.setattr(outbox_mod, "NOTIFICATION_MAX_ATTEMPTS", 1)
    user = _user(db_session, "alice")
    notif = _notif(db_session, user)
    for channel, address in (("ntfy", NTFY_URL), ("telegram", "4711"), ("webhook", HOOK_URL)):
        _outbox(db_session, notif, user, channel=channel, address=address)
    with caplog.at_level(logging.DEBUG):
        assert drain_outbox(db_session) == (0, 3)
    errors = [e.last_error for e in db_session.query(NotificationOutbox)]
    assert sorted(errors) == [
        "ntfy: ConnectError",
        "telegram: ConnectError",
        "webhook: ConnectError",
    ]
    seen = caplog.text + " ".join(errors)
    for secret in (TOKEN, "c2VjcmV0LWF1dGg", "secret-path", "4711"):
        assert secret not in seen


def test_drain_names_only_the_type_of_an_unexpected_error(db_session, wire, monkeypatch):
    def broken(*_a, **_k):
        raise ValueError(f"bad url {HOOK_URL}")

    monkeypatch.setattr(outbox_mod, "send_webhook", broken)
    user = _user(db_session, "alice")
    entry = _outbox(db_session, _notif(db_session, user), user, channel="webhook", address=HOOK_URL)
    drain_outbox(db_session)
    db_session.refresh(entry)
    assert entry.last_error == "webhook: ValueError"


# --- queueing -------------------------------------------------------------------------


def _settings(db, user, *, ntfy=None, webhook=None, channels=()):
    rows = {row: ["desktop", *channels] for row in ("critical", "warning", "info", "ok")}
    db.add(
        NotificationSettings(
            user_id=user.id, ntfy_url=ntfy, webhook_url=webhook, matrix=json.dumps(rows)
        )
    )
    db.commit()


def _queued(db, user):
    rows = db.query(NotificationOutbox).filter(NotificationOutbox.user_id == user.id)
    return sorted((r.channel, r.address, r.severity) for r in rows)


def test_queue_takes_the_targets_of_the_person(db_session, monkeypatch):
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", TOKEN)
    _server(db_session, "srv-1")
    admin = _user(db_session, "boss", is_admin=True, email="a@b.de", telegram_chat_id="4711")
    _sub(db_session, admin, scope_type="all")
    _settings(
        db_session,
        admin,
        ntfy=NTFY_URL,
        webhook=HOOK_URL,
        channels=("email", "ntfy", "telegram", "webhook"),
    )
    assert ingest_event(db_session, _event(severity="critical")) == 1
    assert _queued(db_session, admin) == [
        ("email", "a@b.de", "critical"),
        ("ntfy", NTFY_URL, "critical"),
        ("telegram", "4711", "critical"),
        ("webhook", HOOK_URL, "critical"),
    ]


def test_queue_skips_telegram_without_a_token_and_a_channel_without_target(db_session, monkeypatch):
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
    _server(db_session, "srv-1")
    admin = _user(db_session, "boss", is_admin=True, telegram_chat_id="4711")
    _sub(db_session, admin, scope_type="all")
    _settings(db_session, admin, webhook=HOOK_URL, channels=("ntfy", "telegram", "webhook"))
    assert ingest_event(db_session, _event(severity="critical")) == 1
    assert _queued(db_session, admin) == [("webhook", HOOK_URL, "critical")]


# --- configuration --------------------------------------------------------------------


def test_private_targets_parse_a_cidr_list():
    assert app_config._private_targets(" 192.168.1.0/24, ,fd12::/16,100.64.0.0/10 ") == (
        ipaddress.ip_network("192.168.1.0/24"),
        ipaddress.ip_network("fd12::/16"),
        ipaddress.ip_network("100.64.0.0/10"),
    )
    assert app_config._private_targets("") == ()


@pytest.mark.parametrize("raw", ["192.168.1.5/16", "lan", "192.168.1.0/33", "10.0.0.0/8;x"])
def test_a_wrong_private_target_stops_the_start(raw):
    with pytest.raises(ValueError, match="NOTIFY_PRIVATE_TARGETS"):
        app_config._private_targets(raw)


def test_no_listed_network_looks_up_nothing(monkeypatch):
    def lookup(_h):
        raise AssertionError("no lookup without a listed network")

    monkeypatch.setattr(app_config.socket, "gethostbyname_ex", lookup)
    app_config._warn_own_addresses(())


def test_a_listed_network_with_an_own_address_warns(monkeypatch, caplog):
    monkeypatch.setattr(
        app_config.socket, "gethostbyname_ex", lambda _h: ("box", [], ["198.51.100.7"])
    )
    with caplog.at_level(logging.WARNING, logger="adminhelper.config"):
        app_config._warn_own_addresses((ipaddress.ip_network("198.51.100.0/24"),))
        app_config._warn_own_addresses((ipaddress.ip_network("203.0.113.0/24"),))
    assert [r.getMessage() for r in caplog.records] == [
        "NOTIFY_PRIVATE_TARGETS: 198.51.100.0/24 holds an address of this host; "
        "name the network of the targets alone"
    ]


def test_base64_auth_stays_in_the_url(wire):
    # ntfy takes access as ?auth= (docs.ntfy.sh/publish): the URL goes out as stored.
    send_ntfy(NTFY_URL, "t", "b", "info")
    assert wire.requests[0].url.params["auth"] == "c2VjcmV0LWF1dGg"
    assert base64.b64decode("c2VjcmV0LWF1dGg=") == b"secret-auth"
