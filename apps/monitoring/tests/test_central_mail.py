# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensors smtp and imap of central checks (R-1224) against scripted mail servers on loopback.

Each server records what the client says and whether it spoke out of turn: before
the last line of a greeting, or a second command before the answer to the first.
The ports are ephemeral, so each test maps its port to the protocol under test.
"""

import socket
import ssl
import threading
import time
from collections.abc import Callable
from datetime import timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.verification import Store

from app.central import mail
from app.central.limits import SKIPPED_SPACING_MESSAGE, Limits, RunSkipped

from .test_central_tls import T0, Issued, _issue, _leaf

MX = "mx.example.test"
NOW = T0 + timedelta(days=50)
EHLO = "EHLO [127.0.0.1]"
VALID = "certificate valid until 2026-04-11T00:00:00Z (50.0 days, 50.0 % of lifetime left)"
EHLO_LINES = ("250-mx.example.test", "250-SIZE 10240000", "250-STARTTLS", "250 8BITMIME")


@pytest.fixture(scope="module")
def pki():
    span = {"not_before": T0 - timedelta(days=365), "not_after": T0 + timedelta(days=3650)}
    root = _issue("Test Root", None, ca=True, **span)
    inter = _issue("Test Intermediate", root, ca=True, **span)
    return root, inter


@pytest.fixture(scope="module")
def mx_leaf(pki):
    return _leaf(pki[1], sans=(x509.DNSName(MX),))


class _Peer:
    """The server end of one connection."""

    def __init__(self, conn: socket.socket, context: ssl.SSLContext):
        self.conn: socket.socket = conn
        self.context = context
        self.buffer = b""
        self.commands: list[str] = []
        self.out_of_turn: list[bytes] = []

    def say(self, *lines: str) -> None:
        self.conn.sendall(b"".join(line.encode() + b"\r\n" for line in lines))

    def quiet(self, wait: float) -> None:
        """Records anything the client says within `wait` seconds: it is not its turn."""
        self.conn.settimeout(wait)
        try:
            chunk = self.conn.recv(4096)
        except TimeoutError:
            return
        finally:
            self.conn.settimeout(5)
        if chunk:
            self.out_of_turn.append(chunk)
            self.buffer += chunk

    def hear(self) -> str:
        while b"\n" not in self.buffer:
            chunk = self.conn.recv(4096)
            if not chunk:
                raise EOFError
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b"\n", 1)
        if self.buffer:  # a second command before this one's answer
            self.out_of_turn.append(self.buffer)
        line = raw.rstrip(b"\r").decode("ascii")
        self.commands.append(line)
        return line

    def tls(self) -> None:
        self.conn = self.context.wrap_socket(self.conn, server_side=True)

    def drain(self) -> None:
        """Waits until the client hangs up."""
        while self.conn.recv(4096):
            pass


Script = Callable[[_Peer], None]


class _MailServer:
    """Accepts connections on 127.0.0.1 and runs `script` for each, one after the other."""

    def __init__(self, tmp_path, leaf: Issued, chain: list[x509.Certificate], script: Script):
        pem = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in [leaf.cert, *chain])
        cert_file, key_file = tmp_path / f"chain-{id(self)}.pem", tmp_path / f"key-{id(self)}.pem"
        cert_file.write_bytes(pem)
        key_file.write_bytes(
            leaf.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert_file, key_file)
        self.script = script
        self.peers: list[_Peer] = []
        self.errors: list[BaseException] = []
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def commands(self) -> list[str]:
        return [c for peer in self.peers for c in peer.commands]

    @property
    def out_of_turn(self) -> list[bytes]:
        return [b for peer in self.peers for b in peer.out_of_turn]

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(30)
            peer = _Peer(conn, self.context)
            self.peers.append(peer)
            try:
                self.script(peer)
            except Exception as exc:
                self.errors.append(exc)
            finally:
                peer.conn.close()

    def close(self):
        self.stop.set()
        self.thread.join(10)
        self.listener.close()


@pytest.fixture()
def serve(tmp_path, pki, mx_leaf, monkeypatch):
    servers: list[_MailServer] = []

    def start(script: Script, protocol: mail.Protocol, leaf: Issued | None = None):
        server = _MailServer(tmp_path, leaf or mx_leaf, [pki[1].cert], script)
        monkeypatch.setitem(mail.PROTOCOLS, server.port, protocol)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


class _Turns:
    """Limits stand-in: records the turns asked for and grants them or not."""

    def __init__(self, *, address=True, mail=True):
        self.calls: list[tuple] = []
        self.address, self.mail = address, mail

    def address_turn(self, address):
        self.calls.append(("address", address))
        return self.address

    def mail_turn(self, address, port):
        self.calls.append(("mail", address, port))
        return self.mail


def _probe(server, pki, *, host=MX, limits=None, addresses=("127.0.0.1",)):
    return mail.probe(
        host,
        addresses,
        server.port,
        store=Store([pki[0].cert]),
        now=NOW,
        limits=limits or _Turns(),
    )


# --- scripted servers ---


def _smtp(
    *,
    greeting=("220 mx.example.test ESMTP",),
    pause=0.0,
    ehlo=EHLO_LINES,
    starttls="220 2.0.0 Ready to start TLS",
    after_starttls="",
    ehlo_under_tls=None,
    implicit=False,
) -> Script:
    """A server in the manner of Postfix; `pause` waits after each teaser line of the greeting."""

    def script(peer: _Peer) -> None:
        if implicit:
            peer.tls()
        for line in greeting[:-1]:
            peer.say(line)
            peer.quiet(pause)
        peer.say(greeting[-1])
        secure = implicit
        while True:
            try:
                command = peer.hear()
            except EOFError:
                return
            verb = command.split(" ")[0].upper()
            if verb == "EHLO":
                if secure and ehlo_under_tls is not None:
                    peer.say(*ehlo_under_tls)
                else:
                    peer.say(*[line for line in ehlo if not (secure and "STARTTLS" in line)])
            elif verb == "STARTTLS":
                # In one write with the go-ahead, as an attacker on the path would inject it.
                tail = after_starttls.encode() + b"\r\n" if after_starttls else b""
                peer.conn.sendall(starttls.encode() + b"\r\n" + tail)
                if starttls.startswith("220"):
                    peer.tls()
                    secure = True
            elif verb == "QUIT":
                peer.say("221 2.0.0 Bye")
                return
            else:
                peer.say("502 5.5.2 Error: command not recognized")

    return script


def _imap(
    *,
    greeting="* OK [CAPABILITY IMAP4rev2 STARTTLS LOGINDISABLED] Dovecot ready.",
    capabilities="* CAPABILITY IMAP4rev2 STARTTLS LOGINDISABLED",
    starttls="OK",
    capability_under_tls="OK",
    implicit=False,
) -> Script:
    def script(peer: _Peer) -> None:
        if implicit:
            peer.tls()
        peer.say(greeting)
        secure = implicit
        while True:
            try:
                tag, _, command = peer.hear().partition(" ")
            except EOFError:
                return
            command = command.upper()
            if command == "CAPABILITY":
                caps = capabilities.replace(" STARTTLS", "") if secure else capabilities
                status = capability_under_tls if secure else "OK"
                peer.say(caps, f"{tag} {status} Capability completed.")
            elif command == "STARTTLS":
                peer.say(f"{tag} {starttls} Begin TLS negotiation now.")
                if starttls == "OK":
                    peer.tls()
                    secure = True
            elif command == "LOGOUT":
                peer.say("* BYE Logging out", f"{tag} OK Logout completed.")
                return
            else:
                peer.say(f"{tag} BAD Error in IMAP command")

    return script


def _pop3(
    *,
    greeting="+OK Dovecot ready.",
    capa=("+OK", "TOP", "UIDL", "RESP-CODES", "USER", "SASL PLAIN", "."),
) -> Script:
    def script(peer: _Peer) -> None:
        peer.tls()
        peer.say(greeting)
        while True:
            try:
                command = peer.hear().upper()
            except EOFError:
                return
            if command == "CAPA":
                peer.say(*capa)
            elif command == "QUIT":
                peer.say("+OK Logging out.")
                return
            else:
                peer.say("-ERR Unknown command")

    return script


# --- SMTP ---


def test_smtp_waits_for_the_whole_greeting_and_leaves_after_starttls(serve, pki):
    greeting = ("220-mx.example.test ESMTP", "220-please wait", "220 mx.example.test ESMTP")
    server = serve(_smtp(greeting=greeting, pause=0.3), mail.SMTP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("ok", True)
    assert result.message == f"SMTP port {server.port}: {VALID}"
    assert server.commands == [EHLO, "STARTTLS", EHLO, "QUIT"]
    assert server.out_of_turn == []
    d = result.details
    assert (d["host"], d["address"], d["port"]) == (MX, "127.0.0.1", server.port)
    assert (d["protocol"], d["starttls"]) == ("SMTP", True)
    assert d["greeting"] == "220-mx.example.test ESMTP"
    assert d["tls_version"] in {"TLSv1.2", "TLSv1.3"}
    assert d["san"] == [MX]
    assert result.metrics == {"days_left": 50.0, "lifetime_pct": 50.0}
    server.close()
    assert server.errors == []


def test_smtp_on_465_speaks_tls_first(serve, pki):
    server = serve(_smtp(implicit=True), mail.SMTPS)

    result = _probe(server, pki)

    assert result.status == "ok"
    assert result.message == f"SMTP port {server.port}: {VALID}"
    assert server.commands == [EHLO, "QUIT"]
    assert result.details["starttls"] is False
    assert result.details["greeting"] == "220 mx.example.test ESMTP"


def test_the_last_reply_line_may_end_right_after_its_code(serve, pki):
    ehlo = ("250-mx.example.test", "250-STARTTLS", "250")
    server = serve(_smtp(ehlo=ehlo), mail.SMTP)

    assert _probe(server, pki).status == "ok"


def test_a_554_greeting_is_a_refusal_answered_with_quit(serve, pki):
    server = serve(_smtp(greeting=("554 5.7.1 Service unavailable; client blocked",)), mail.SMTP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert result.message == (
        f"SMTP port {server.port}: the server refuses the connection: "
        "554 5.7.1 Service unavailable; client blocked"
    )
    assert server.commands == ["QUIT"]
    assert "tls_version" not in result.details


def test_another_greeting_than_220_is_critical(serve, pki):
    server = serve(_smtp(greeting=("421 4.3.2 Service shutting down",)), mail.SMTP)

    result = _probe(server, pki)

    assert result.status == "critical"
    assert result.message == f"SMTP port {server.port}: greeting 421 4.3.2 Service shutting down"
    assert server.commands == ["QUIT"]


def test_a_server_without_starttls_is_critical(serve, pki):
    ehlo = ("250-mx.example.test", "250 8BITMIME")
    server = serve(_smtp(ehlo=ehlo), mail.SMTP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert result.message == f"SMTP port {server.port}: the server offers no STARTTLS"
    assert server.commands == [EHLO, "QUIT"]


def test_a_refused_starttls_is_critical(serve, pki):
    server = serve(_smtp(starttls="454 4.7.0 TLS not available"), mail.SMTP)

    result = _probe(server, pki)

    assert result.status == "critical"
    assert (
        result.message == f"SMTP port {server.port}: STARTTLS answered 454 4.7.0 TLS not available"
    )
    assert server.commands == [EHLO, "STARTTLS", "QUIT"]


def test_plaintext_after_the_starttls_go_ahead_is_discarded(serve, pki):
    # Read as the answer to the EHLO under TLS, the injected line would fail the run.
    server = serve(_smtp(after_starttls="554 5.7.0 injected"), mail.SMTP)

    result = _probe(server, pki)

    assert result.status == "ok"
    assert server.commands == [EHLO, "STARTTLS", EHLO, "QUIT"]


def test_a_failure_after_the_handshake_keeps_the_certificate_details(serve, pki):
    server = serve(_smtp(ehlo_under_tls=("554 5.7.0 go away",)), mail.SMTP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert result.message == (
        f"SMTP port {server.port}: EHLO under TLS answered 554 5.7.0 go away; {VALID}"
    )
    assert result.details["san"] == [MX]
    assert result.details["tls_version"] in {"TLSv1.2", "TLSv1.3"}
    assert server.commands == [EHLO, "STARTTLS", EHLO, "QUIT"]


def test_a_certificate_for_another_name_is_critical(serve, pki):
    leaf = _leaf(pki[1], sans=(x509.DNSName("other.example.test"),))
    server = serve(_smtp(), mail.SMTP, leaf=leaf)

    result = _probe(server, pki)

    assert result.status == "critical"
    assert result.message.startswith(f"SMTP port {server.port}: certificate not trusted for {MX}: ")


def test_a_failed_handshake_is_critical_and_reached(serve, pki):
    def script(peer: _Peer) -> None:
        peer.say("220 mx.example.test ESMTP")
        peer.hear()
        peer.say(*EHLO_LINES)
        peer.hear()
        peer.say("220 2.0.0 Ready to start TLS")
        peer.conn.recv(4096)  # the ClientHello
        peer.conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")

    server = serve(script, mail.SMTP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert result.message.startswith(f"SMTP port {server.port}: TLS handshake failed: ")
    assert "tls_version" not in result.details
    assert server.commands == [EHLO, "STARTTLS"]


def test_a_silent_server_times_out(serve, pki, monkeypatch):
    # Tests the greeting's time limit itself, hence the short one.
    monkeypatch.setattr(mail, "GREETING_TIMEOUT_S", 1.0)
    server = serve(lambda peer: peer.drain(), mail.SMTP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert result.message == f"SMTP port {server.port}: no greeting within 1 s"


def test_a_server_that_hangs_up_before_its_greeting_is_critical(serve, pki):
    server = serve(lambda peer: None, mail.SMTP)

    result = _probe(server, pki)

    assert result.status == "critical"
    assert result.message == (
        f"SMTP port {server.port}: the server closed the connection instead of its greeting"
    )


def test_another_protocol_on_the_port_is_no_smtp_reply(serve, pki):
    server = serve(_smtp(greeting=("SSH-2.0-OpenSSH_9.6\x1b[0m",)), mail.SMTP)

    result = _probe(server, pki)

    assert result.status == "critical"
    assert result.message == (
        f"SMTP port {server.port}: greeting is no SMTP reply: SSH-2.0-OpenSSH_9.6?[0m"
    )
    assert server.commands == []


def test_a_reply_that_changes_its_code_is_critical(serve, pki):
    server = serve(_smtp(ehlo=("250-mx.example.test", "220 STARTTLS")), mail.SMTP)

    result = _probe(server, pki)

    assert result.message == (
        f"SMTP port {server.port}: reply to EHLO changes its code within the reply: 220 STARTTLS"
    )


def test_an_endless_line_is_cut_off(serve, pki):
    def script(peer: _Peer) -> None:
        peer.conn.sendall(b"220-" + b"a" * (mail.MAX_LINE + 100))
        peer.drain()

    server = serve(script, mail.SMTP)

    result = _probe(server, pki)

    assert result.message == (
        f"SMTP port {server.port}: greeting: a line longer than {mail.MAX_LINE} bytes"
    )


def test_a_dribbling_server_cannot_hold_the_run_past_the_deadline(serve, pki, monkeypatch):
    # Tests the conversation's deadline itself, hence the short one.
    monkeypatch.setattr(mail, "DEADLINE_S", 1.0)

    def script(peer: _Peer) -> None:
        for _ in range(50):
            try:
                peer.say("220-still there")
            except OSError:
                return
            time.sleep(0.1)

    server = serve(script, mail.SMTP)
    started = time.monotonic()

    result = _probe(server, pki)

    assert time.monotonic() - started < 3
    assert result.message == f"SMTP port {server.port}: the conversation took longer than 1 s"


class _Sock:
    def __init__(self, name):
        self.name = name

    def getsockname(self):
        return self.name


@pytest.mark.parametrize(
    ("name", "literal"),
    [
        (("192.0.2.25", 40000), "[192.0.2.25]"),
        (("2001:db8::25", 40000, 0, 0), "[IPv6:2001:db8::25]"),
        (("fe80::1%eth0", 40000, 0, 2), "[IPv6:fe80::1]"),
    ],
)
def test_ehlo_names_the_address_of_our_end(name, literal):
    assert mail._ehlo_name(_Sock(name)) == literal


# --- IMAP and POP3 ---


def test_imap_on_143_asks_for_starttls_and_logs_out(serve, pki):
    server = serve(_imap(), mail.IMAP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("ok", True)
    assert result.message == f"IMAP port {server.port}: {VALID}"
    assert server.commands == ["a1 CAPABILITY", "a2 STARTTLS", "a3 CAPABILITY", "a4 LOGOUT"]
    assert server.out_of_turn == []
    d = result.details
    assert (d["protocol"], d["starttls"]) == ("IMAP", True)
    assert d["greeting"] == "* OK [CAPABILITY IMAP4rev2 STARTTLS LOGINDISABLED] Dovecot ready."
    server.close()
    assert server.errors == []


def test_imap_on_993_speaks_tls_first(serve, pki):
    server = serve(_imap(implicit=True), mail.IMAPS)

    result = _probe(server, pki)

    assert result.status == "ok"
    assert server.commands == ["a1 CAPABILITY", "a4 LOGOUT"]
    assert result.details["starttls"] is False


def test_an_imap_bye_greeting_is_a_refusal(serve, pki):
    server = serve(_imap(greeting="* BYE Too many connections"), mail.IMAP)

    result = _probe(server, pki)

    assert result.message == (
        f"IMAP port {server.port}: the server refuses the connection: * BYE Too many connections"
    )
    assert server.commands == []


@pytest.mark.parametrize(
    ("greeting", "capabilities"),
    [
        ("* OK ready", "* CAPABILITY IMAP4rev2 LOGINDISABLED"),
        # Past the login already: STARTTLS is out of reach (RFC 9051 §6.2.1).
        ("* PREAUTH logged in", "* CAPABILITY IMAP4rev2 STARTTLS"),
    ],
)
def test_imap_without_starttls_is_critical(serve, pki, greeting, capabilities):
    server = serve(_imap(greeting=greeting, capabilities=capabilities), mail.IMAP)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert result.message == f"IMAP port {server.port}: the server offers no STARTTLS"
    assert server.commands == ["a1 CAPABILITY", "a2 LOGOUT"]


def test_a_refused_imap_starttls_is_critical(serve, pki):
    server = serve(_imap(starttls="NO"), mail.IMAP)

    result = _probe(server, pki)

    assert result.message == f"IMAP port {server.port}: STARTTLS answered NO"
    assert server.commands == ["a1 CAPABILITY", "a2 STARTTLS", "a3 LOGOUT"]


@pytest.mark.parametrize(
    ("script", "protocol", "said"),
    [
        (_imap(starttls="\x00\x1b[2J"), mail.IMAP, "STARTTLS answered ??[2J"),
        (
            _imap(capability_under_tls="\x00\x1b[2J"),
            mail.IMAP,
            "CAPABILITY under TLS answered ??[2J",
        ),
        (
            _imap(capability_under_tls="\x00\x1b[2J", implicit=True),
            mail.IMAPS,
            "CAPABILITY answered ??[2J",
        ),
    ],
)
def test_an_imap_status_reaches_the_message_printable(serve, pki, script, protocol, said):
    server = serve(script, protocol)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("critical", True)
    assert said in result.message
    assert result.message.isprintable()


def test_another_protocol_is_no_imap_greeting(serve, pki):
    server = serve(_imap(greeting="220 mx.example.test ESMTP"), mail.IMAP)

    result = _probe(server, pki)

    assert result.message == (
        f"IMAP port {server.port}: greeting is no IMAP greeting: 220 mx.example.test ESMTP"
    )
    assert server.commands == []


def test_pop3_on_995_asks_for_capa_and_quits(serve, pki):
    server = serve(_pop3(), mail.POP3S)

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("ok", True)
    assert result.message == f"POP3 port {server.port}: {VALID}"
    assert server.commands == ["CAPA", "QUIT"]
    assert (result.details["protocol"], result.details["starttls"]) == ("POP3", False)
    server.close()
    assert server.errors == []


def test_pop3_without_capa_is_fine(serve, pki):
    server = serve(_pop3(capa=("-ERR Unknown command",)), mail.POP3S)

    result = _probe(server, pki)

    assert result.status == "ok"
    assert server.commands == ["CAPA", "QUIT"]


def test_a_pop3_err_greeting_is_a_refusal(serve, pki):
    server = serve(_pop3(greeting="-ERR [SYS/TEMP] Too many connections"), mail.POP3S)

    result = _probe(server, pki)

    # On 995 the refusal comes under TLS: the certificate is judged all the same.
    assert result.message == (
        f"POP3 port {server.port}: the server refuses the connection: "
        f"-ERR [SYS/TEMP] Too many connections; {VALID}"
    )
    assert result.status == "critical"
    assert server.commands == []


def test_a_capa_reply_of_another_protocol_is_critical(serve, pki):
    server = serve(_pop3(capa=("* OK what",)), mail.POP3S)

    result = _probe(server, pki)

    assert result.message.startswith(
        f"POP3 port {server.port}: reply to CAPA is no POP3 reply: * OK what; "
    )
    assert server.commands == ["CAPA", "QUIT"]


# --- ports, addresses, spacing ---


def _closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as s:
        return s.getsockname()[1]


def test_a_port_without_a_mail_protocol_is_unknown_and_asks_for_no_turn():
    turns = _Turns()

    result = mail.probe(MX, ("127.0.0.1",), 2525, limits=turns)

    assert (result.status, result.message, result.reached) == (
        "unknown",
        "no mail protocol on port 2525",
        False,
    )
    assert turns.calls == []


def test_the_next_address_is_tried_when_one_refuses(serve, pki):
    server = serve(_smtp(), mail.SMTP)
    turns = _Turns()

    # Nothing listens on 127.0.0.2 at this port: the server is bound to 127.0.0.1.
    result = _probe(server, pki, addresses=("127.0.0.2", "127.0.0.1"), limits=turns)

    assert result.status == "ok"
    assert result.details["address"] == "127.0.0.1"
    assert turns.calls == [
        ("address", "127.0.0.2"),
        ("mail", "127.0.0.2", server.port),
        ("address", "127.0.0.1"),
        ("mail", "127.0.0.1", server.port),
    ]


def test_no_connection_is_critical_and_not_reached(pki, monkeypatch):
    port = _closed_port()
    monkeypatch.setitem(mail.PROTOCOLS, port, mail.SMTP)
    addresses = ("127.0.0.2", "127.0.0.3", "127.0.0.4", "127.0.0.5")

    result = mail.probe(MX, addresses, port, store=Store([pki[0].cert]), limits=_Turns())

    assert (result.status, result.reached) == ("critical", False)
    assert result.message.startswith(f"no connection to {MX} port {port}: 127.0.0.2: ")
    assert "127.0.0.5" not in result.message
    assert result.details == {"host": MX, "port": port}


@pytest.mark.parametrize(
    ("refused", "asked"), [("address", ["address"]), ("mail", ["address", "mail"])]
)
def test_an_address_or_mail_port_without_its_turn_skips_the_run(serve, pki, refused, asked):
    server = serve(_smtp(), mail.SMTP)
    turns = _Turns(**{refused: False})

    with pytest.raises(RunSkipped, match=SKIPPED_SPACING_MESSAGE):
        _probe(server, pki, limits=turns)

    assert [c[0] for c in turns.calls] == asked
    server.close()
    assert server.peers == []


def test_one_connection_per_address_and_port_in_15_minutes(serve, pki):
    clock = [1000.0]
    limits = Limits(clock=lambda: clock[0], sleep=lambda _s: None)
    server = serve(_smtp(), mail.SMTP)

    assert _probe(server, pki, limits=limits).status == "ok"
    clock[0] += 14 * 60
    with pytest.raises(RunSkipped, match=SKIPPED_SPACING_MESSAGE):
        _probe(server, pki, limits=limits)
    clock[0] += 60
    assert _probe(server, pki, limits=limits).status == "ok"

    server.close()
    assert len(server.peers) == 2
