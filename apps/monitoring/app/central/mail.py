# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensors smtp and imap of central checks (R-1224): the certificate of a mail server.

The sensor talks to the server as a mail client would and leaves before asking
anything of it: SMTP greeting, EHLO, STARTTLS, EHLO, QUIT (465: TLS first); IMAP
greeting, CAPABILITY, STARTTLS, CAPABILITY, LOGOUT (993: TLS first); POP3 on 995
greeting, CAPA, QUIT. Never MAIL, RCPT, VRFY or AUTH. Nothing goes out before the
server's turn: postscreen sends a multi-line greeting whose first lines are a
teaser and drops a client that speaks before the last one, and it announces no
pipelining, so each command waits for its reply. One connection to an address and
port in 15 minutes at most, over all checks (Limits.mail_turn), keeps the sensor
below what postscreen and fail2ban count. The certificate is judged as the sensor
tls judges it; ari and caa stay with that sensor.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.x509.verification import Store

from app.central import tls
from app.central.limits import LIMITS, SKIPPED_SPACING_MESSAGE, Limits, RunSkipped
from app.central.tls import SensorResult

GREETING_TIMEOUT_S = 30.0
REPLY_TIMEOUT_S = 15.0
QUIT_TIMEOUT_S = 5.0
# The whole conversation, so that a server dribbling bytes cannot hold a slot.
DEADLINE_S = 60.0
MAX_LINE = 8192
MAX_LINES = 64
MAX_TEXT = 200


class _Failure(Exception):
    """The conversation ended before it was through; the message says where."""


def _overdue() -> str:
    return f"the conversation took longer than {DEADLINE_S:.0f} s"


class _Conversation:
    """One connection: lines in, commands out, TLS when it is time."""

    def __init__(self, sock: socket.socket, host: str) -> None:
        self.sock: socket.socket = sock
        self.host = host
        self.started = time.monotonic()
        self.buffer = b""
        self.greeting: str | None = None
        self.tls_version: str | None = None
        self.chain: list[bytes] | None = None

    def start_tls(self) -> None:
        # Whatever came in plaintext after the server's go-ahead is discarded unread
        # (RFC 3207 §4.2): it could pose as an answer given under TLS.
        self.buffer = b""
        try:
            wrapped = tls.wrap(self.sock, self.host)
        except OSError as exc:  # ssl.SSLError and timeouts included
            raise _Failure(f"TLS handshake failed: {_reason(exc)}") from None
        self.sock = wrapped
        self.tls_version = wrapped.version()
        self.chain = wrapped.get_unverified_chain() or []

    def send(self, line: str, name: str) -> None:
        self._timeout(REPLY_TIMEOUT_S)
        try:
            self.sock.sendall(line.encode("ascii") + b"\r\n")
        except OSError as exc:
            raise _Failure(f"sending {name} failed: {_reason(exc)}") from None

    def line(self, timeout: float, what: str) -> str:
        """The next line without its CRLF; `what` names the awaited reply in failures."""
        while True:
            end = self.buffer.find(b"\n")
            if end >= 0:
                raw, self.buffer = self.buffer[:end], self.buffer[end + 1 :]
                if len(raw) > MAX_LINE:
                    raise _Failure(f"{what}: a line longer than {MAX_LINE} bytes")
                return raw.rstrip(b"\r").decode("ascii", "replace")
            if len(self.buffer) > MAX_LINE:
                raise _Failure(f"{what}: a line longer than {MAX_LINE} bytes")
            wait = self._timeout(timeout)
            try:
                chunk = self.sock.recv(4096)
            except TimeoutError:
                if wait < timeout:  # cut short by the deadline, not the server's turn
                    raise _Failure(_overdue()) from None
                raise _Failure(f"no {what} within {wait:.0f} s") from None
            except OSError as exc:
                raise _Failure(f"{what}: {_reason(exc)}") from None
            if not chunk:
                raise _Failure(f"the server closed the connection instead of its {what}")
            self.buffer += chunk

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _timeout(self, timeout: float) -> float:
        left = DEADLINE_S - (time.monotonic() - self.started)
        if left <= 0:
            raise _Failure(_overdue())
        wait = min(timeout, left)
        self.sock.settimeout(wait)
        return wait


# --- SMTP (RFC 5321, STARTTLS RFC 3207, implicit TLS RFC 8314) ---


def _smtp_reply(conv: _Conversation, timeout: float, what: str) -> tuple[int, list[str]]:
    """A reply of one or more lines: all but the last carry `code-` (RFC 5321 §4.2.1)."""
    lines: list[str] = []
    while len(lines) < MAX_LINES:
        line = conv.line(timeout, what)
        code = line[:3]
        if not (len(code) == 3 and code.isascii() and code.isdigit() and code[0] in "2345"):
            raise _Failure(f"{what} is no SMTP reply: {_show(line)}")
        if lines and code != lines[0][:3]:
            raise _Failure(f"{what} changes its code within the reply: {_show(line)}")
        lines.append(line)
        # The last line has a space after the code, or nothing: clients must accept both.
        if line[3:4] != "-":
            return int(code), lines
    raise _Failure(f"{what} is longer than {MAX_LINES} lines")


def _smtp_command(conv: _Conversation, command: str) -> tuple[int, list[str]]:
    name = command.split()[0]
    conv.send(command, name)
    return _smtp_reply(conv, REPLY_TIMEOUT_S, f"reply to {name}")


def _smtp_quit(conv: _Conversation) -> None:
    # Hanging up costs a client nothing with postscreen; the reply is awaited as
    # RFC 5321 §4.1.1.10 asks, and its absence is no finding.
    try:
        conv.send("QUIT", "QUIT")
        _smtp_reply(conv, QUIT_TIMEOUT_S, "reply to QUIT")
    except _Failure:
        pass


def _ehlo_name(sock: socket.socket) -> str:
    """The address literal of our end (RFC 5321 §4.1.4): a container has no name of its own
    that resolves, and asking DNS for one would cost a lookup per run."""
    ip = ipaddress.ip_address(sock.getsockname()[0].split("%")[0])
    return f"[IPv6:{ip}]" if ip.version == 6 else f"[{ip}]"


def _smtp(conv: _Conversation, implicit: bool) -> None:
    ehlo = f"EHLO {_ehlo_name(conv.sock)}"
    if implicit:
        conv.start_tls()
    code, lines = _smtp_reply(conv, GREETING_TIMEOUT_S, "greeting")
    conv.greeting = _show(lines[0])
    if code == 554:
        # RFC 5321 §3.1: the server refuses this client and waits for its QUIT.
        _smtp_quit(conv)
        raise _Failure(f"the server refuses the connection: {_show(lines[-1])}")
    if code != 220:
        _smtp_quit(conv)
        raise _Failure(f"greeting {_show(lines[-1])}")
    code, lines = _smtp_command(conv, ehlo)
    if code != 250:
        _smtp_quit(conv)
        raise _Failure(f"EHLO answered {_show(lines[-1])}")
    if not implicit:
        if "STARTTLS" not in {line[4:].split(" ")[0].upper() for line in lines[1:]}:
            _smtp_quit(conv)
            raise _Failure("the server offers no STARTTLS")
        code, lines = _smtp_command(conv, "STARTTLS")
        if code != 220:
            _smtp_quit(conv)
            raise _Failure(f"STARTTLS answered {_show(lines[-1])}")
        conv.start_tls()
        # What the server offered before TLS is void now (RFC 3207 §4.2): ask again.
        code, lines = _smtp_command(conv, ehlo)
        if code != 250:
            _smtp_quit(conv)
            raise _Failure(f"EHLO under TLS answered {_show(lines[-1])}")
    _smtp_quit(conv)


# --- IMAP (RFC 9051) and POP3 (RFC 1939, CAPA RFC 2449) ---


def _imap_command(conv: _Conversation, tag: str, command: str) -> tuple[str, list[str]]:
    """The tagged status (OK, NO, BAD) and the untagged lines before it."""
    conv.send(f"{tag} {command}", command)
    what = f"reply to {command}"
    untagged: list[str] = []
    while len(untagged) < MAX_LINES:
        line = conv.line(REPLY_TIMEOUT_S, what)
        if line.startswith(f"{tag} "):
            # The status goes into the message, so it is shown like every server line.
            return _show(line[len(tag) + 1 :].split(" ")[0].upper()), untagged
        untagged.append(line)
    raise _Failure(f"{what} is longer than {MAX_LINES} lines")


def _imap_logout(conv: _Conversation, tag: str) -> None:
    try:
        conv.send(f"{tag} LOGOUT", "LOGOUT")
        for _ in range(MAX_LINES):
            if conv.line(QUIT_TIMEOUT_S, "reply to LOGOUT").startswith(f"{tag} "):
                return
    except _Failure:
        pass


def _capabilities(untagged: list[str]) -> set[str]:
    return {
        word.upper()
        for line in untagged
        if line.upper().startswith("* CAPABILITY ")
        for word in line.split(" ")[2:]
    }


def _imap(conv: _Conversation, implicit: bool) -> None:
    if implicit:
        conv.start_tls()
    greeting = conv.line(GREETING_TIMEOUT_S, "greeting")
    conv.greeting = _show(greeting)
    state = greeting.split(" ")[1].upper() if greeting.startswith("* ") else ""
    if state == "BYE":
        raise _Failure(f"the server refuses the connection: {_show(greeting)}")
    if state not in ("OK", "PREAUTH"):
        raise _Failure(f"greeting is no IMAP greeting: {_show(greeting)}")
    status, untagged = _imap_command(conv, "a1", "CAPABILITY")
    if status != "OK":
        _imap_logout(conv, "a2")
        raise _Failure(f"CAPABILITY answered {status or 'nothing'}")
    if not implicit:
        # STARTTLS exists only before login (RFC 9051 §6.2.1); PREAUTH is past it.
        if state == "PREAUTH" or "STARTTLS" not in _capabilities(untagged):
            _imap_logout(conv, "a2")
            raise _Failure("the server offers no STARTTLS")
        status, _ = _imap_command(conv, "a2", "STARTTLS")
        if status != "OK":
            _imap_logout(conv, "a3")
            raise _Failure(f"STARTTLS answered {status or 'nothing'}")
        conv.start_tls()
        status, _ = _imap_command(conv, "a3", "CAPABILITY")
        if status != "OK":
            _imap_logout(conv, "a4")
            raise _Failure(f"CAPABILITY under TLS answered {status or 'nothing'}")
    _imap_logout(conv, "a4")


def _pop3_quit(conv: _Conversation) -> None:
    try:
        conv.send("QUIT", "QUIT")
        conv.line(QUIT_TIMEOUT_S, "reply to QUIT")
    except _Failure:
        pass


def _pop3(conv: _Conversation, _implicit: bool) -> None:
    """POP3 only on 995, where TLS comes first (RFC 8314 §3.3)."""
    conv.start_tls()
    greeting = conv.line(GREETING_TIMEOUT_S, "greeting")
    conv.greeting = _show(greeting)
    if greeting.startswith("-ERR"):
        raise _Failure(f"the server refuses the connection: {_show(greeting)}")
    if not greeting.startswith("+OK"):
        raise _Failure(f"greeting is no POP3 greeting: {_show(greeting)}")
    conv.send("CAPA", "CAPA")
    first = conv.line(REPLY_TIMEOUT_S, "reply to CAPA")
    if first.startswith("+OK"):
        # A multi-line answer ends with a line holding one dot (RFC 1939 §3).
        for _ in range(MAX_LINES):
            if conv.line(REPLY_TIMEOUT_S, "reply to CAPA") == ".":
                break
        else:
            raise _Failure(f"reply to CAPA is longer than {MAX_LINES} lines")
    elif not first.startswith("-ERR"):  # -ERR: CAPA not implemented (RFC 2449 §5)
        _pop3_quit(conv)
        raise _Failure(f"reply to CAPA is no POP3 reply: {_show(first)}")
    _pop3_quit(conv)


@dataclass(frozen=True)
class Protocol:
    name: str
    implicit_tls: bool
    talk: Callable[[_Conversation, bool], None]


SMTP = Protocol("SMTP", False, _smtp)
SMTPS = Protocol("SMTP", True, _smtp)
IMAP = Protocol("IMAP", False, _imap)
IMAPS = Protocol("IMAP", True, _imap)
POP3S = Protocol("POP3", True, _pop3)
# The ports check_configs allows the sensors smtp and imap.
PROTOCOLS: dict[int, Protocol] = {
    25: SMTP,
    587: SMTP,
    465: SMTPS,
    143: IMAP,
    993: IMAPS,
    995: POP3S,
}


def probe(
    host: str,
    addresses: tuple[str, ...],
    port: int,
    *,
    store: Store | None = None,
    now: datetime | None = None,
    limits: Limits | None = None,
) -> SensorResult:
    """Talks to the first of `addresses` that accepts a connection and judges its certificate
    for `host`. Raises RunSkipped when an address or its mail port may not be contacted yet."""
    protocol = PROTOCOLS.get(port)
    if protocol is None:
        return SensorResult("unknown", f"no mail protocol on port {port}", False)
    limits = limits or LIMITS
    now = now or datetime.now(timezone.utc)
    failures: list[str] = []
    for address in addresses[: tls.MAX_ADDRESSES]:
        if not limits.address_turn(address) or not limits.mail_turn(address, port):
            raise RunSkipped(SKIPPED_SPACING_MESSAGE)
        try:
            sock = socket.create_connection((address, port), timeout=tls.CONNECT_TIMEOUT_S)
        except OSError as exc:
            failures.append(f"{address}: {_reason(exc)}")
            continue
        return _talk(sock, protocol, host, address, port, store or tls.default_store(), now)
    return SensorResult(
        "critical",
        f"no connection to {host} port {port}: " + "; ".join(failures),
        reached=False,
        details={"host": host, "port": port},
    )


def _talk(
    sock: socket.socket,
    protocol: Protocol,
    host: str,
    address: str,
    port: int,
    store: Store,
    now: datetime,
) -> SensorResult:
    conv = _Conversation(sock, host)
    failure = None
    try:
        protocol.talk(conv, protocol.implicit_tls)
    except _Failure as exc:
        failure = str(exc)
    finally:
        conv.close()
    details: dict = {"host": host, "address": address, "port": port, "protocol": protocol.name}
    details["starttls"] = not protocol.implicit_tls
    if conv.greeting is not None:
        details["greeting"] = conv.greeting
    if conv.tls_version is not None:
        details["tls_version"] = conv.tls_version
    label = f"{protocol.name} port {port}"
    if conv.chain is None:
        return SensorResult("critical", f"{label}: {failure}"[:MAX_TEXT], True, {}, details)
    result, _leaf = tls.judge(conv.chain, host, details, store, now)
    if failure is None:
        return SensorResult(
            result.status, f"{label}: {result.message}", True, result.metrics, result.details
        )
    message = f"{label}: {failure}; {result.message}"
    return SensorResult("critical", message, True, result.metrics, result.details)


def _show(line: str) -> str:
    """A line of the server as the details and messages may carry it."""
    return "".join(c if c.isprintable() else "?" for c in line)[:MAX_TEXT]


def _reason(exc: BaseException) -> str:
    return str(getattr(exc, "reason", None) or str(exc) or type(exc).__name__)[:MAX_TEXT]
