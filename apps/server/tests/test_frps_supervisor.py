# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frps supervisor (apps/frps/frps-supervisor.sh) starts frps only from a configuration that
passed every check: a non-empty frps.toml in the layout the server generates, with auth.method
token, a token of at least 16 characters, TLS forced and the three TLS paths pointing into the
PKI directory, webServer.port off the published bind port; the three files there, the
certificate files intact, the leaf not expired and matching its key; frps verify green. Input
files are read only as regular files and within a time limit; a symlink or anything else is
unreadable. A valid input is copied into current/ of the working directory (0700, files 0600)
with its TLS paths pointed there, and frps runs from current/, each time only once the copy has
passed the check again. An invalid input starts nothing, or frps from the last valid current/
(degraded); a missing frps.toml removes current/. Every status file it writes (0644) passes the
server's reader.

After the start it polls the input: a change that stayed the same for two polls is taken over
like at the start, restarting frps only for a new valid input, and one that keeps changing shows
as unstable; frps exiting on its own is restarted after a growing delay, three exits in a row
make a crash loop; TERM and INT stop frps and leave no process behind; `health` judges the
state.

The script runs under sh with a stub frps on PATH. Some tests run it in the frps image with the
real frps; they skip when Docker or the pinned base image is not at hand."""

import contextlib
import hashlib
import itertools
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.modules.frp.config_generator import _FRPS_CERT_DIR, generate_frps_toml
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.supervisor_status import SupervisorStatus, read_supervisor_status

FRPS_DIR = Path(__file__).resolve().parents[2] / "frps"
SCRIPT = FRPS_DIR / "frps-supervisor.sh"
TOKEN = "test-token-0123456789abcdef"
NEW_TOKEN = "next-token-fedcba9876543210"
PEMS = ("frps.crt", "frps.key", "ca.crt")
WAIT = 10.0
HEX64 = re.compile(r"[0-9a-f]{64}")
# The log line of a poll that sees an input it has not taken over yet.
CHANGED = "input changed"

STUB = """#!/bin/sh
# Stands in for frps: records every call; verify keeps a copy of the file it was given and fails
# while $STUB_DIR/verify-fails exists. A run records the sha256 of the file it was started with
# and exits at once while $STUB_DIR/crashes counts down; otherwise it ignores TERM while
# $STUB_DIR/ignore-term exists, records its pid and stays up until it is stopped.
printf '%s\\n' "$*" >> "$STUB_DIR/calls"
if [ "$1" = verify ]; then
    cp "$3" "$STUB_DIR/verified.toml"
    [ ! -e "$STUB_DIR/verify-fails" ]
    exit
fi
sha256sum < "$2" | cut -d ' ' -f 1 >> "$STUB_DIR/ran"
crashes=$(cat "$STUB_DIR/crashes" 2>/dev/null || echo 0)
if [ "$crashes" -gt 0 ]; then
    echo $((crashes - 1)) > "$STUB_DIR/crashes"
    exit 3
fi
if [ -e "$STUB_DIR/ignore-term" ]; then
    trap '' TERM
fi
echo $$ >> "$STUB_DIR/pids"
exec sleep 600
"""


def _key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _cert_pem(key, name: str, issuer_key, issuer: str, *, days: tuple[int, int], ca: bool):
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=days[0]))
        .not_valid_after(now + timedelta(days=days[1]))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(issuer_key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.fixture(scope="module")
def pems() -> dict[str, bytes]:
    ca_key, leaf_key = _key(), _key()
    return {
        "ca.crt": _cert_pem(ca_key, "test ca", ca_key, "test ca", days=(-1, 30), ca=True),
        "frps.crt": _cert_pem(leaf_key, "frps", ca_key, "test ca", days=(-1, 30), ca=False),
        "frps.key": _key_pem(leaf_key),
        "renewed.crt": _cert_pem(leaf_key, "frps", ca_key, "test ca", days=(-1, 60), ca=False),
        "expired.crt": _cert_pem(leaf_key, "frps", ca_key, "test ca", days=(-10, -1), ca=False),
        "other.key": _key_pem(_key()),
        "other.crt": _cert_pem(_key(), "other ca", ca_key, "test ca", days=(-1, 30), ca=True),
    }


def _cfg(**fields) -> FrpServerConfig:
    values = {
        "id": "c1",
        "name": "c1",
        "server_addr": "frps.example.net",
        "bind_port": 7000,
        "auth_token": TOKEN,
    }
    values.update(fields)
    return FrpServerConfig(**values)


def _toml(pki: Path, **fields) -> str:
    """frps.toml as the server generates it, its TLS paths moved into the test's PKI directory."""
    toml = generate_frps_toml(_cfg(**fields))
    assert toml.count(f'"{_FRPS_CERT_DIR}/') == 3
    return toml.replace(f'"{_FRPS_CERT_DIR}/', f'"{pki}/')


class Box:
    """Input, working and state directory of one supervisor, plus the stub frps it finds."""

    def __init__(self, root: Path, pems: dict[str, bytes]):
        self.root = root
        self.pems = pems
        self.config = root / "input" / "frps.toml"
        self.pki = root / "pki"
        self.active = root / "active"
        self.current = self.active / "current"
        self.state = root / "state"
        self.status_file = self.state / "status.json"
        self.stub = root / "stub"
        self.log = root / "supervisor.log"
        self.procs: list[subprocess.Popen] = []
        self.supervisor: subprocess.Popen | None = None
        bin_dir = root / "bin"
        for directory in (self.config.parent, self.pki, self.stub, bin_dir):
            directory.mkdir()
        (bin_dir / "frps").write_text(STUB)
        (bin_dir / "frps").chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FRPS_CONFIG": str(self.config),
            "FRPS_PKI_DIR": str(self.pki),
            "FRPS_ACTIVE_DIR": str(self.active),
            "FRPS_STATE_DIR": str(self.state),
            "STUB_DIR": str(self.stub),
            # One poll an hour, so a test of the start sees the start alone; the tests of
            # the loop poll every second (see _polling).
            "FRPS_POLL_SECONDS": "3600",
        }

    def write_input(self, toml: str | None = None, pems: dict[str, bytes] | None = None):
        self.config.write_text(_toml(self.pki) if toml is None else toml, encoding="utf-8")
        for name in PEMS:
            (self.pki / name).write_bytes({**self.pems, **(pems or {})}[name])

    def replace_in_config(self, old: str, new: str):
        text = self.config.read_text()
        assert text.count(old) == 1, old
        self.config.write_text(text.replace(old, new))

    def run(self, *, frps: bool) -> dict:
        """Starts the supervisor; returns the status file once it is written and, with frps=True,
        once frps was started."""
        self.status_file.unlink(missing_ok=True)
        (self.stub / "calls").unlink(missing_ok=True)
        with self.log.open("ab") as log:
            proc = subprocess.Popen(
                ["/bin/sh", str(SCRIPT)],
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.procs.append(proc)
        self.supervisor = proc
        deadline = time.monotonic() + WAIT
        while not (self.status_file.exists() and (self.frps_runs() or not frps)):
            assert proc.poll() is None, f"supervisor exited ({proc.returncode}):\n{self._log()}"
            assert time.monotonic() < deadline, f"no status within {WAIT}s:\n{self._log()}"
            time.sleep(0.05)
        return json.loads(self.status_file.read_text())

    def stop(self):
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        self.procs.clear()

    def read(self) -> SupervisorStatus:
        status = read_supervisor_status(self.status_file)
        assert status.state not in ("missing", "unreadable"), self.status_file.read_text()
        return status

    def doc(self) -> dict:
        return json.loads(self.status_file.read_text())

    def wait_until(self, check, what: str, timeout: float = WAIT):
        """Polls check() until it holds; the supervisor has to stay up meanwhile."""
        deadline = time.monotonic() + timeout
        while not check():
            assert self.supervisor.poll() is None, (
                f"supervisor exited ({self.supervisor.returncode}):\n{self._log()}"
            )
            assert time.monotonic() < deadline, f"not {what} within {timeout}s:\n{self._log()}"
            time.sleep(0.05)

    def wait_state(self, state: str, timeout: float = WAIT) -> SupervisorStatus:
        self.wait_until(lambda: self.read().state == state, state, timeout)
        return self.read()

    def wait_events(self, count: int, timeout: float = WAIT) -> SupervisorStatus:
        self.wait_until(lambda: len(self.read().events) >= count, f"{count} events", timeout)
        return self.read()

    def wait_polls(self, count: int = 3):
        """Returns once count more polls wrote the status: each one a new heartbeat, as the
        loop polls once a second at the most."""
        seen = {self.doc()["heartbeat"]}

        def polled() -> bool:
            seen.add(self.doc()["heartbeat"])
            return len(seen) > count

        self.wait_until(polled, f"{count} polls", WAIT + 2 * count)

    def calls(self) -> list[str]:
        calls = self.stub / "calls"
        return calls.read_text().splitlines() if calls.exists() else []

    def frps_runs(self) -> bool:
        return any(call.startswith("-c ") for call in self.calls())

    def runs(self) -> int:
        return self.calls().count(f"-c {self.current}/frps.toml")

    def ran(self) -> list[str]:
        """The sha256 of the file each frps run was started with."""
        ran = self.stub / "ran"
        return ran.read_text().split() if ran.exists() else []

    def pids(self) -> list[int]:
        """The frps runs that stayed up, oldest first."""
        pids = self.stub / "pids"
        return [int(pid) for pid in pids.read_text().split()] if pids.exists() else []

    def health(self) -> int:
        return self.once("health").returncode

    def once(self, *args: str) -> subprocess.CompletedProcess:
        """Runs the script to its end, in a session the teardown kills should it not end."""
        proc = subprocess.Popen(
            ["/bin/sh", str(SCRIPT), *args],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        self.procs.append(proc)
        out, err = proc.communicate(timeout=WAIT)
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def _log(self) -> str:
        return self.log.read_text() if self.log.exists() else ""


@pytest.fixture()
def box(tmp_path, pems):
    box = Box(tmp_path, pems)
    yield box
    box.stop()


def _events(status: SupervisorStatus) -> list[tuple]:
    return [(e.seq, e.event, e.reason, e.token_changed) for e in status.events]


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_valid_input_is_copied_into_current_and_frps_runs_from_there(box):
    box.write_input()
    # Modes the copies must not take over.
    box.config.chmod(0o644)
    for name in PEMS:
        (box.pki / name).chmod(0o755)
    # Modes the supervisor has to correct: the server reads the status under another UID, the
    # working directory holds the token and the key.
    box.state.mkdir(mode=0o700)
    box.state.chmod(0o700)
    box.active.mkdir()
    box.active.chmod(0o755)

    doc = box.run(frps=True)

    status = box.read()
    assert (status.state, status.reason, status.stale) == ("running", "none", False)
    assert _events(status) == [(1, "started", "none", False)]
    assert HEX64.fullmatch(doc["appliedHash"]) and doc["rejectedHash"] is None
    assert box.calls() == [
        f"verify -c {box.active}/next/frps.toml",
        f"-c {box.current}/frps.toml",
    ]
    expected = box.config.read_text().replace(f'"{box.pki}/', f'"{box.current}/')
    assert (box.current / "frps.toml").read_text() == expected
    assert (box.stub / "verified.toml").read_text() == expected
    for name in PEMS:
        assert (box.current / name).read_bytes() == box.pems[name]
    assert [p.name for p in box.active.iterdir()] == ["current"]
    assert _mode(box.active) == 0o700
    assert _mode(box.current) == 0o700
    assert {p.name: _mode(p) for p in box.current.iterdir()} == {
        name: 0o600 for name in (*PEMS, "frps.toml", "applied.sha256")
    }
    assert _mode(box.state) == 0o755
    assert _mode(box.status_file) == 0o644
    assert [p.name for p in box.state.iterdir()] == ["status.json"]


def test_a_token_of_16_characters_is_enough(box):
    box.write_input(_toml(box.pki, auth_token="k" * 16))
    box.run(frps=True)
    assert box.read().state == "running"


def _remove(name: str):
    return lambda box: (box.pki / name).unlink()


def _write(name: str, content: bytes):
    return lambda box: (box.pki / name).write_bytes(content)


def _move(name: str):
    return lambda box: box.replace_in_config(f'"{box.pki}/{name}"', f'"/srv/elsewhere/{name}"')


def _cut_bundle(name: str, second: str):
    """name followed by a second certificate, cut short inside the second one."""
    return lambda box: _write(name, (box.pems[name] + box.pems[second])[:-60])(box)


RULES = {
    "frps.toml missing": ("config_missing", lambda box: box.config.unlink()),
    "frps.toml empty": ("config_missing", lambda box: box.config.write_text("")),
    "token of 15 characters": (
        "token_invalid",
        lambda box: box.replace_in_config(f'"{TOKEN}"', '"' + "k" * 15 + '"'),
    ),
    "TLS not forced": (
        "tls_not_forced",
        lambda box: box.replace_in_config("force = true", "force = false"),
    ),
    "certFile elsewhere": ("cert_paths", _move("frps.crt")),
    "keyFile elsewhere": ("cert_paths", _move("frps.key")),
    "trustedCaFile elsewhere": ("cert_paths", _move("ca.crt")),
    "frps.crt missing": ("cert_missing", _remove("frps.crt")),
    "frps.key missing": ("cert_missing", _remove("frps.key")),
    "ca.crt missing": ("cert_missing", _remove("ca.crt")),
    "frps.key empty": ("cert_missing", _write("frps.key", b"")),
    "frps.crt cut short": ("cert_missing", _cut_bundle("frps.crt", "ca.crt")),
    "ca.crt cut short": ("cert_missing", _cut_bundle("ca.crt", "other.crt")),
    "leaf expired": ("cert_expired", lambda box: _write("frps.crt", box.pems["expired.crt"])(box)),
    "key of another leaf": (
        "cert_key_mismatch",
        lambda box: _write("frps.key", box.pems["other.key"])(box),
    ),
    "frps verify fails": ("verify_failed", lambda box: (box.stub / "verify-fails").touch()),
}


@pytest.mark.parametrize("case", list(RULES))
def test_an_input_that_breaks_a_rule_starts_nothing(box, case):
    reason, damage = RULES[case]
    box.write_input()
    damage(box)

    doc = box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", reason, ())
    assert not box.frps_runs()
    assert list(box.active.iterdir()) == []
    assert doc["appliedHash"] is None
    if reason == "config_missing":
        assert doc["rejectedHash"] is None
    else:
        assert HEX64.fullmatch(doc["rejectedHash"])


def _skip_as_root():
    if os.geteuid() == 0:
        pytest.skip("root reads a file without read permission")


def _symlink(name: str):
    """The input file replaced by a symlink to a file with the same, valid content."""

    def damage(box):
        path = box.config if name == "frps.toml" else box.pki / name
        target = box.root / f"elsewhere-{name}"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)

    return damage


def _unreadable(box):
    _skip_as_root()
    box.config.chmod(0)


def _fifo(name: str):
    def damage(box):
        (box.pki / name).unlink()
        os.mkfifo(box.pki / name)

    return damage


def _directory(name: str):
    def damage(box):
        (box.pki / name).unlink()
        (box.pki / name).mkdir()

    return damage


# Stands in for cat or sha256sum: blocks on one file, as reading a FIFO swapped in after the
# check of the file type would; any other call goes to the real program.
HANGS = """#!/bin/sh
for arg in "$@"; do
    if [ "$arg" = "{path}" ]; then exec sleep 600; fi
done
exec {real} "$@"
"""


def _hanging(name: str):
    def damage(box):
        box.env["FRPS_READ_SECONDS"] = "1"
        for program in ("cat", "sha256sum"):
            real = shutil.which(program)
            assert real, program
            stub = box.root / "bin" / program
            stub.write_text(HANGS.format(path=box.pki / name, real=real))
            stub.chmod(0o755)

    return damage


UNREADABLE = {
    "frps.toml a symlink": _symlink("frps.toml"),
    "frps.key a symlink": _symlink("frps.key"),
    "frps.toml without read permission": _unreadable,
    "frps.crt a FIFO": _fifo("frps.crt"),
    "ca.crt a directory": _directory("ca.crt"),
    "a read of frps.crt that does not end": _hanging("frps.crt"),
}


@pytest.mark.parametrize("case", list(UNREADABLE))
def test_an_input_file_that_cannot_be_read_as_a_regular_file_starts_nothing(box, case):
    box.write_input()
    UNREADABLE[case](box)

    doc = box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", "input_unreadable", ())
    assert not box.frps_runs()
    assert list(box.active.iterdir()) == []
    assert doc["appliedHash"] is None and HEX64.fullmatch(doc["rejectedHash"])
    # Nothing but the supervisor's own lines: no error of a tool that tried to read the file.
    assert all(line.startswith("[frps-supervisor] ") for line in box._log().splitlines())


def _edit(change):
    return lambda box: box.config.write_text(change(box.config.read_text()))


TABLE = "[transport.tls]\n"


def _generated(**fields):
    return lambda box: box.write_input(_toml(box.pki, **fields))


def _extra(extra: dict):
    return _generated(extra_config=json.dumps(extra))


LAYOUT = {
    "template comment around the table": (
        "verify_failed",
        _edit(lambda t: t.replace(TABLE, "{{/*\n" + TABLE) + "*/}}\n"),
    ),
    "template action as the token": (
        "verify_failed",
        _edit(lambda t: t.replace(f'"{TOKEN}"', '"{{print}}{{print}}{{print}}"')),
    ),
    "multi-line string around the table": (
        "verify_failed",
        _edit(lambda t: t.replace(TABLE, 'subDomainHost = """\n' + TABLE) + '"""\n'),
    ),
    "[common] line": ("verify_failed", _edit(lambda t: "[common]\n" + t)),
    "second table": ("verify_failed", _edit(lambda t: t + "\n[webServer]\nport = 7500\n")),
    "table header twice": ("verify_failed", _edit(lambda t: t + TABLE)),
    "key twice at top level": (
        "verify_failed",
        _edit(lambda t: t.replace("bindPort = 7000\n", "bindPort = 7000\nbindPort = 7001\n")),
    ),
    "key twice in the table": ("verify_failed", _edit(lambda t: t + "force = true\n")),
    "other key in the table": ("verify_failed", _edit(lambda t: t + 'serverName = "frps"\n')),
    "literal string": (
        "verify_failed",
        _edit(lambda t: t.replace('auth.method = "token"', "auth.method = 'token'")),
    ),
    "backslash in a string": (
        "verify_failed",
        _edit(
            lambda t: t.replace(
                "bindPort = 7000\n", 'bindPort = 7000\nsubDomainHost = "a\\u0062"\n'
            )
        ),
    ),
    "indented line": ("verify_failed", _edit(lambda t: t.replace("bindPort", "  bindPort"))),
    "control character in a string": (
        "verify_failed",
        _edit(
            lambda t: t.replace("bindPort = 7000\n", 'bindPort = 7000\nsubDomainHost = "a\x00b"\n')
        ),
    ),
    "CRLF line ends": ("verify_failed", _edit(lambda t: t.replace("\n", "\r\n"))),
    "auth.method other than token": (
        "token_invalid",
        _edit(lambda t: t.replace('auth.method = "token"', 'auth.method = "oidc"')),
    ),
    "auth.additionalScopes in extra_config": (
        "token_invalid",
        _extra({"auth.additionalScopes": "HeartBeats"}),
    ),
    "auth.oidc.clientID in extra_config": ("token_invalid", _extra({"auth.oidc.clientID": "c1"})),
    "transport.tls.force in extra_config": (
        "verify_failed",
        _extra({"transport.tls.force": False}),
    ),
    "sshTunnelGateway.bindPort in extra_config": (
        "verify_failed",
        _extra({"sshTunnelGateway.bindPort": 7022}),
    ),
    "SshTunnelGateway.bindPort in extra_config": (
        "verify_failed",
        _extra({"SshTunnelGateway.bindPort": 7022}),
    ),
    "bindport next to bindPort": ("verify_failed", _extra({"bindport": 99999})),
    "Auth.method in extra_config": ("verify_failed", _extra({"Auth.method": "bogus"})),
    "Transport.tls.force in extra_config": (
        "verify_failed",
        _extra({"Transport.tls.force": False}),
    ),
    "key not on the list": ("verify_failed", _extra({"enablePrometheus": True})),
    "webServer.port 443": ("verify_failed", _generated(dashboard_port=443)),
    "webServer.port +443.0": (
        "verify_failed",
        lambda box: box.write_input(
            _toml(box.pki, dashboard_port=7500).replace(
                "webServer.port = 7500", "webServer.port = +443.0"
            )
        ),
    ),
    "webServer.port equal to bindPort": ("verify_failed", _generated(dashboard_port=7000)),
    "bindPort missing": ("verify_failed", _edit(lambda t: t.replace("bindPort = 7000\n", ""))),
    "auth.method missing": (
        "token_invalid",
        _edit(lambda t: t.replace('auth.method = "token"\n', "")),
    ),
}


@pytest.mark.parametrize("case", list(LAYOUT))
def test_only_the_layout_the_server_generates_is_accepted(box, case):
    reason, change = LAYOUT[case]
    box.write_input()
    change(box)

    box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", reason, ())
    assert box.calls() == []


@pytest.mark.parametrize(("published", "accepted"), [("7100", False), ("7101", True)])
def test_webserver_port_does_not_take_the_published_bind_port_either(box, published, accepted):
    # FRP_BIND_PORT: the port compose publishes on the host, also when bindPort is another.
    box.env["FRP_BIND_PORT"] = published
    box.write_input(_toml(box.pki, dashboard_port=7100))

    box.run(frps=accepted)

    status = box.read()
    expected = ("running", "none") if accepted else ("waiting", "verify_failed")
    assert (status.state, status.reason) == expected
    assert box.frps_runs() is accepted


# Every field the generator writes, extra_config with a value of each allowed type.
FULL = {
    "vhost_https_port": 8443,
    "subdomain_host": "example.net",
    "max_ports_per_client": 8,
    "dashboard_port": 7500,
    "dashboard_user": "admin-\u00fc",
    "dashboard_password": "d" * 24,
}
EXTRA = {
    "transport.maxPoolCount": 5,
    "transport.tcpMux": True,
    "transport.tcpMuxKeepaliveInterval": 30,
    "transport.heartbeatTimeout": -1,
    "transport.tcpKeepalive": 7200,
    "userConnTimeout": 10,
    "log.level": "info",
    "log.maxDays": 3,
}


def test_the_full_output_of_the_generator_is_accepted(box):
    toml = _toml(box.pki, **FULL, extra_config=json.dumps(EXTRA))
    top_keys = re.search(r'^TOP_KEYS="([^"]*)"', SCRIPT.read_text(), re.M)
    assert top_keys
    keys = [line.split(" = ")[0] for line in toml.split(TABLE)[0].splitlines() if line]
    assert sorted(keys) == sorted(top_keys[1].split())
    box.write_input(
        toml,
        pems={
            "frps.crt": box.pems["frps.crt"] + box.pems["ca.crt"],
            "ca.crt": box.pems["ca.crt"] + box.pems["other.crt"],
        },
    )

    box.run(frps=True)

    assert (box.read().state, box.read().reason) == ("running", "none")
    expected = toml.replace(f'"{box.pki}/', f'"{box.current}/')
    assert (box.stub / "verified.toml").read_text(encoding="utf-8") == expected


def test_an_invalid_input_starts_frps_from_the_last_valid_copy(box):
    box.write_input()
    applied = box.run(frps=True)["appliedHash"]
    box.stop()
    previous = (box.current / "frps.toml").read_text()
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})

    doc = box.run(frps=True)

    status = box.read()
    assert (status.state, status.reason) == ("degraded", "cert_expired")
    assert _events(status) == [(1, "rejected", "cert_expired", False)]
    assert doc["appliedHash"] == applied
    assert HEX64.fullmatch(doc["rejectedHash"]) and doc["rejectedHash"] != applied
    assert box.calls()[-1] == f"-c {box.current}/frps.toml"
    assert (box.current / "frps.toml").read_text() == previous
    assert (box.current / "frps.crt").read_bytes() == box.pems["frps.crt"]


def test_a_new_valid_input_replaces_the_copy_at_the_next_start(box):
    box.write_input()
    first = box.run(frps=True)
    box.stop()
    box.write_input(_toml(box.pki, auth_token="n" * 32))

    second = box.run(frps=True)

    assert box.read().state == "running"
    assert second["appliedHash"] != first["appliedHash"]
    assert second["boot"] != first["boot"]
    assert 'auth.token = "' + "n" * 32 + '"' in (box.current / "frps.toml").read_text()
    assert [p.name for p in box.active.iterdir()] == ["current"]


def test_a_removed_frps_toml_removes_the_copy_and_starts_nothing(box):
    box.write_input()
    box.run(frps=True)
    box.stop()
    box.config.unlink()

    doc = box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason) == ("stopped", "config_missing")
    assert _events(status) == [(1, "stopped", "config_missing", False)]
    assert not box.frps_runs()
    assert not box.current.exists()
    assert doc["appliedHash"] is None

    box.stop()
    box.run(frps=False)
    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", "config_missing", ())


def test_a_swap_cut_short_between_its_two_renames_is_rolled_back_at_the_next_start(box):
    box.write_input()
    box.run(frps=True)
    box.stop()
    box.current.rename(box.active / "prev")
    box.write_input(_toml(box.pki, auth_token="k" * 15))

    box.run(frps=True)

    assert (box.read().state, box.read().reason) == ("degraded", "token_invalid")
    assert [p.name for p in box.active.iterdir()] == ["current"]
    assert box.calls()[-1] == f"-c {box.current}/frps.toml"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _change_copy(box: Box) -> str:
    """Changes the copy frps runs from (frps can write there): TLS no longer forced. Returns
    the sha256 of the changed file."""
    copy = box.current / "frps.toml"
    text = copy.read_text()
    assert text.count("force = true") == 1
    copy.write_text(text.replace("force = true", "force = false"))
    return _sha256(copy.read_text())


def test_a_changed_copy_is_dropped_and_not_started_for_an_invalid_input_either(box):
    box.write_input()
    box.run(frps=True)
    box.stop()
    _change_copy(box)
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})

    box.run(frps=False)

    # As for an invalid input without a valid copy.
    status = box.read()
    assert (status.state, status.reason, status.events) == ("waiting", "cert_expired", ())
    assert not box.frps_runs()
    assert list(box.active.iterdir()) == []


def _polling(box: Box, *, valid: bool = True, **env: str) -> dict:
    """Starts a supervisor that polls every second, from a valid input or from none."""
    box.env.update({"FRPS_POLL_SECONDS": "1", **env})
    if valid:
        box.write_input()
    return box.run(frps=valid)


def _alive(pid: int) -> bool:
    """Whether the process exists, a zombie included (a child nobody has waited for)."""
    return Path(f"/proc/{pid}").exists()


def _session(sid: int) -> list[str]:
    """/proc/<pid>/stat of every process in the session; Box starts each supervisor in one of
    its own, and only a process that calls setsid leaves it."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            line = (entry / "stat").read_text()
        except OSError:
            continue
        # pid (comm) state ppid pgrp session …; comm may hold spaces and parentheses.
        if int(line.rsplit(")", 1)[1].split()[3]) == sid:
            found.append(line)
    return found


def _wait_gone(sid: int):
    deadline = time.monotonic() + WAIT
    while left := _session(sid):
        assert time.monotonic() < deadline, f"still running:\n{''.join(left)}"
        time.sleep(0.05)


def _verify_then_run(box: Box) -> list[str]:
    return [f"verify -c {box.active}/next/frps.toml", f"-c {box.current}/frps.toml"]


STARTED = (1, "started", "none", False)


def test_a_valid_input_that_shows_up_later_starts_frps(box):
    _polling(box, valid=False)
    assert (box.read().state, box.read().reason) == ("waiting", "config_missing")
    assert box.health() == 0

    box.write_input()

    status = box.wait_state("running")
    assert _events(status) == [STARTED]
    assert box.calls() == _verify_then_run(box)
    assert box.health() == 0


def test_an_input_written_again_unchanged_restarts_nothing(box):
    first = _polling(box)

    box.write_input()
    box.wait_polls(3)

    assert box.calls() == _verify_then_run(box)
    assert _events(box.read()) == [STARTED]
    assert box.doc()["appliedHash"] == first["appliedHash"]
    assert box.pids() and _alive(box.pids()[0])


CHANGES = {
    "new token": (lambda box: box.write_input(_toml(box.pki, auth_token=NEW_TOKEN)), True),
    "other port limit": (
        lambda box: box.write_input(_toml(box.pki, max_ports_per_client=8)),
        False,
    ),
    "renewed certificate": (
        lambda box: box.write_input(pems={"frps.crt": box.pems["renewed.crt"]}),
        False,
    ),
}


@pytest.mark.parametrize("case", list(CHANGES))
def test_a_valid_change_restarts_frps_once_from_the_new_copy(box, case):
    change, token_changed = CHANGES[case]
    first = _polling(box)

    change(box)
    box.wait_events(2)
    box.wait_polls(2)

    status = box.read()
    assert (status.state, status.reason) == ("running", "none")
    assert _events(status) == [STARTED, (2, "applied", "none", token_changed)]
    assert box.calls() == _verify_then_run(box) * 2
    old, new = box.pids()
    assert not _alive(old) and _alive(new)
    doc = box.doc()
    assert HEX64.fullmatch(doc["appliedHash"]) and doc["appliedHash"] != first["appliedHash"]
    expected = box.config.read_text().replace(f'"{box.pki}/', f'"{box.current}/')
    assert (box.current / "frps.toml").read_text() == expected
    for name in PEMS:
        assert (box.current / name).read_bytes() == (box.pki / name).read_bytes()
    assert [p.name for p in box.active.iterdir()] == ["current"]
    # The token goes nowhere but into the copy for frps: not into the log, the status or an
    # argument of frps.
    seen = box._log() + box.status_file.read_text() + "\n".join(box.calls())
    assert TOKEN not in seen and NEW_TOKEN not in seen


def test_a_half_written_input_is_taken_over_only_once_it_stays_the_same(box):
    # Two seconds between polls: the time the test has to finish the file once the supervisor
    # saw the first half.
    _polling(box, FRPS_POLL_SECONDS="2")
    full = _toml(box.pki, auth_token=NEW_TOKEN)
    changes = box._log().count(CHANGED)

    box.config.write_text(full[: full.index(TABLE)])
    box.wait_until(lambda: box._log().count(CHANGED) > changes, "the first half seen")
    # Well inside the two seconds: a supervisor that took the first half over at once has
    # copied it by now.
    time.sleep(0.5)
    box.config.write_text(full)

    status = box.wait_events(2, timeout=3 * WAIT)
    assert _events(status) == [STARTED, (2, "applied", "none", True)]
    assert box.calls() == _verify_then_run(box) * 2


def test_an_invalid_change_is_rejected_once_and_frps_runs_on(box):
    first = _polling(box)

    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})
    box.wait_state("degraded")
    rejected = box.doc()["rejectedHash"]
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})
    box.wait_polls(3)

    status = box.read()
    assert status.reason == "cert_expired"
    assert _events(status) == [STARTED, (2, "rejected", "cert_expired", False)]
    assert HEX64.fullmatch(rejected) and box.doc()["rejectedHash"] == rejected
    assert box.doc()["appliedHash"] == first["appliedHash"]
    assert box.health() == 1

    box.write_input(_toml(box.pki, auth_token="k" * 15))
    box.wait_events(3)
    status = box.read()
    assert (status.state, status.reason) == ("degraded", "token_invalid")
    assert _events(status)[2:] == [(3, "rejected", "token_invalid", False)]

    # Back to the input frps runs from: nothing to restart.
    box.write_input()
    box.wait_state("running")
    box.wait_polls(2)

    assert len(box.read().events) == 3
    assert box.runs() == 1
    assert len(box.pids()) == 1 and _alive(box.pids()[0])
    assert (box.doc()["appliedHash"], box.doc()["rejectedHash"]) == (first["appliedHash"], None)
    assert box.health() == 0


def test_an_input_that_turns_unreadable_is_rejected_and_logged_once(box):
    _skip_as_root()
    _polling(box)
    lines = len(box._log().splitlines())

    box.config.chmod(0)
    box.wait_state("degraded")
    box.wait_polls(3)

    status = box.read()
    assert status.reason == "input_unreadable"
    assert _events(status) == [STARTED, (2, "rejected", "input_unreadable", False)]
    assert box._log().splitlines()[lines:] == [
        "[frps-supervisor] input changed, taking it over once it stays the same",
        "[frps-supervisor] configuration rejected: input_unreadable",
        "[frps-supervisor] state degraded (input_unreadable)",
    ]
    assert box.runs() == 1 and _alive(box.pids()[0])

    # Readable again, the input frps runs from: nothing to restart.
    box.config.chmod(0o600)
    status = box.wait_state("running")
    assert (status.reason, len(status.events)) == ("none", 2)
    assert box.runs() == 1


def _replace(path: Path, text: str):
    """Writes path in one go, so that every poll sees a whole file."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


@contextlib.contextmanager
def _changing(box: Box):
    """Rewrites frps.toml faster than the polls, so that each of them sees another input."""
    stop = threading.Event()

    def change():
        for limit in itertools.count(1):
            if stop.is_set():
                return
            _replace(box.config, _toml(box.pki, max_ports_per_client=limit))
            time.sleep(0.3)

    changer = threading.Thread(target=change)
    changer.start()
    try:
        yield
    finally:
        stop.set()
        changer.join()


def _unstable(box: Box) -> SupervisorStatus:
    """The status once the input counts as unstable and two more polls saw it change."""
    box.wait_until(lambda: box.read().reason == "input_unstable", "unstable", 2 * WAIT)
    box.wait_polls(2)
    return box.read()


@pytest.mark.parametrize("running", [True, False], ids=["frps running", "no copy"])
def test_an_input_that_keeps_changing_is_unstable_until_it_stays_the_same(box, running):
    if not running:
        for name in PEMS:
            (box.pki / name).write_bytes(box.pems[name])
    _polling(box, valid=running, FRPS_UNSTABLE_SECONDS="3")
    events, calls = _events(box.read()), box.calls()
    changes = box._log().count(CHANGED)
    unstable = (len(events) + 1, "rejected", "input_unstable", False)

    with _changing(box):
        status = _unstable(box)
        assert status.state == ("degraded" if running else "waiting")
        # One event for the series, nothing taken over, one log line for the change.
        assert (_events(status), box.calls()) == ([*events, unstable], calls)
        assert box._log().count(CHANGED) == changes + 1
        assert box.health() == (1 if running else 0)

    _replace(box.config, _toml(box.pki, auth_token=NEW_TOKEN))
    status = box.wait_events(len(events) + 2)

    assert (status.state, status.reason) == ("running", "none")
    taken = ("applied", "none", True) if running else ("started", "none", False)
    assert _events(status)[len(events) + 1 :] == [(len(events) + 2, *taken)]
    assert 'auth.token = "' + NEW_TOKEN + '"' in (box.current / "frps.toml").read_text()

    # Once the input stayed the same, the next series is one event again.
    with _changing(box):
        status = _unstable(box)
        assert status.state == "degraded"
        assert _events(status)[len(events) + 2 :] == [
            (len(events) + 3, "rejected", "input_unstable", False)
        ]


@pytest.mark.parametrize("removal", ["deleted", "emptied"])
def test_a_removed_input_stops_frps_and_a_new_one_starts_it_again(box, removal):
    _polling(box)

    if removal == "deleted":
        box.config.unlink()
    else:
        box.config.write_text("")
    status = box.wait_state("stopped")

    assert status.reason == "config_missing"
    assert _events(status) == [STARTED, (2, "stopped", "config_missing", False)]
    (pid,) = box.pids()
    assert not _alive(pid)
    assert list(box.active.iterdir()) == []
    assert box.doc()["appliedHash"] is None
    assert box.health() == 0

    box.write_input()
    status = box.wait_state("running")

    assert _events(status)[2:] == [(3, "started", "none", False)]
    assert _alive(box.pids()[-1])


def _delays(log: str) -> list[int]:
    return [int(d) for d in re.findall(r"restarting it in (\d+)s", log)]


def test_frps_that_keeps_exiting_is_restarted_ever_later_until_it_is_a_crash_loop(box):
    (box.stub / "crashes").write_text("99")
    box.env["FRPS_BACKOFF_MAX"] = "4"

    _polling(box)
    status = box.wait_state("crashloop", timeout=3 * WAIT)

    # 2, 4, then capped at 4: the third exit within the window makes the crash loop.
    log = box._log()
    assert _delays(log[: log.index("state crashloop")]) == [2, 4, 4]
    assert (status.reason, _events(status)) == ("none", [STARTED, (2, "crashed", "none", False)])
    assert box.pids() == []
    assert box.health() == 1


def test_a_crash_loop_ends_once_frps_stays_up_for_the_window(box):
    # Four exits, the fourth within the crash loop; the fifth run stays up.
    (box.stub / "crashes").write_text("4")
    box.env.update(FRPS_BACKOFF_MAX="1", FRPS_CRASH_WINDOW="10")

    _polling(box)
    box.wait_state("crashloop", timeout=2 * WAIT)
    status = box.wait_state("running", timeout=4 * WAIT)

    assert _events(status) == [STARTED, (2, "crashed", "none", False)]
    assert _delays(box._log()) == [1, 1, 1, 1]
    assert box.runs() == 5
    assert _alive(box.pids()[-1])
    assert box.health() == 0


def test_frps_that_exits_starts_again_from_the_input_never_from_a_changed_copy(box):
    _polling(box)
    box.wait_until(box.pids, "frps up")
    changed = _change_copy(box)

    os.kill(box.pids()[0], signal.SIGKILL)

    # The copy fails the check before the restart and goes; the input is taken over anew.
    status = box.wait_events(2)
    assert (status.state, status.reason) == ("running", "none")
    assert _events(status) == [STARTED, (2, "started", "none", False)]
    box.wait_until(lambda: len(box.pids()) == 2, "frps up again")
    assert box.calls() == _verify_then_run(box) * 2
    expected = box.config.read_text().replace(f'"{box.pki}/', f'"{box.current}/')
    assert (box.current / "frps.toml").read_text() == expected
    assert box.ran() == [_sha256(expected)] * 2 and changed not in box.ran()
    assert _alive(box.pids()[-1])


def test_frps_that_exits_stays_down_with_a_changed_copy_and_an_invalid_input(box):
    _polling(box)
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})
    box.wait_state("degraded")
    changed = _change_copy(box)

    os.kill(box.pids()[0], signal.SIGKILL)

    # As for an invalid input without a valid copy.
    status = box.wait_state("waiting")
    assert (status.reason, _events(status)) == (
        "cert_expired",
        [STARTED, (2, "rejected", "cert_expired", False)],
    )
    box.wait_polls(3)
    assert box.runs() == 1 and changed not in box.ran()
    assert list(box.active.iterdir()) == []
    assert box.health() == 0


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["TERM", "INT"])
@pytest.mark.parametrize("valid", [True, False], ids=["frps running", "waiting"])
def test_a_signal_stops_frps_and_leaves_no_process_behind(box, sig, valid):
    # The hourly poll of Box: a sleep the supervisor left behind would still be there.
    if valid:
        box.write_input()
    box.run(frps=valid)
    if valid:
        box.wait_until(box.pids, "frps up")

    box.supervisor.send_signal(sig)

    assert box.supervisor.wait(timeout=WAIT) == 0
    _wait_gone(box.supervisor.pid)
    assert box.runs() == (1 if valid else 0)


def test_frps_that_ignores_term_is_killed(box):
    (box.stub / "ignore-term").touch()
    box.env["FRPS_STOP_SECONDS"] = "1"
    box.write_input()
    box.run(frps=True)
    box.wait_until(box.pids, "frps up")

    box.supervisor.send_signal(signal.SIGTERM)

    assert box.supervisor.wait(timeout=WAIT) == 0
    _wait_gone(box.supervisor.pid)
    assert "killing it" in box._log()


@pytest.mark.parametrize(
    ("knob", "value"),
    [
        ("FRPS_POLL_SECONDS", "0"),
        ("FRPS_POLL_SECONDS", "0.5"),
        ("FRPS_BACKOFF_MAX", "x"),
        ("FRPS_STOP_SECONDS", "-1"),
        ("FRPS_CRASH_WINDOW", "08"),
        ("FRPS_READ_SECONDS", "0"),
        ("FRPS_UNSTABLE_SECONDS", "30s"),
    ],
)
def test_a_time_that_is_no_whole_number_of_seconds_stops_the_supervisor(box, knob, value):
    box.write_input()
    box.env[knob] = value

    result = box.once()

    assert result.returncode == 1 and knob in result.stderr
    assert box.calls() == [] and not box.status_file.exists()


@pytest.mark.parametrize("value", ["0", "-1", "7000x", "65536"])
def test_a_published_bind_port_that_is_no_port_stops_the_supervisor(box, value):
    box.write_input()
    box.env["FRP_BIND_PORT"] = value

    result = box.once()

    assert result.returncode == 1 and "FRP_BIND_PORT" in result.stderr
    assert box.calls() == [] and not box.status_file.exists()


def _status_doc(state: str) -> str:
    """A status file as the supervisor writes it: compact, one line."""
    stamp = "2026-10-16T12:00:00Z"
    doc = {
        "v": 1,
        "boot": "0123456789abcdef",
        "heartbeat": stamp,
        "state": state,
        "reason": "none",
        "since": stamp,
        "appliedHash": None,
        "rejectedHash": None,
        "events": [
            {"seq": 1, "event": "started", "at": stamp, "reason": "none", "tokenChanged": False}
        ],
    }
    return json.dumps(doc, separators=(",", ":")) + "\n"


@pytest.mark.parametrize(
    ("state", "healthy"),
    [
        ("waiting", True),
        ("running", True),
        ("stopped", True),
        ("degraded", False),
        ("crashloop", False),
        (None, False),
    ],
)
def test_health_is_good_while_waiting_running_or_stopped(box, state, healthy):
    box.state.mkdir()
    if state:
        box.status_file.write_text(_status_doc(state))
        assert box.read().state == state

    assert (box.health() == 0) is healthy
    assert not box.active.exists()
    assert box.calls() == []


def test_the_supervisor_expects_the_tls_files_where_the_server_points_frps():
    assert f'FRPS_PKI_DIR="${{FRPS_PKI_DIR:-{_FRPS_CERT_DIR}}}"' in SCRIPT.read_text()


def _image() -> tuple[str, str, list[str]]:
    """Base image, the script's place in the image and the entrypoint, as in the Dockerfile."""
    dockerfile = (FRPS_DIR / "Dockerfile").read_text()
    base = re.search(r"^FROM (\S+)$", dockerfile, re.M)
    target = re.search(r"^COPY frps-supervisor\.sh (\S+)$", dockerfile, re.M)
    entrypoint = re.search(r"^ENTRYPOINT (\[.*\])$", dockerfile, re.M)
    assert base and target and entrypoint, dockerfile
    return base[1], target[1], json.loads(entrypoint[1])


class Container:
    """A container of the frps base image that runs the supervisor as the Dockerfile sets it
    up, its input and working directories bind-mounted from the test's directory."""

    def __init__(self, docker: str, root: Path, entrypoint: list[str]):
        self.docker = docker
        self.name = f"frps-supervisor-test-{uuid.uuid4().hex[:12]}"
        self.frp, self.pki, self.state, self.active = (
            root / name for name in ("frp", "pki", "state", "active")
        )
        self.status_file = self.state / "status.json"
        self.health = [docker, "exec", self.name, *entrypoint, "health"]

    def logs(self) -> str:
        return subprocess.run(
            [self.docker, "logs", self.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout

    def read(self) -> SupervisorStatus:
        return read_supervisor_status(self.status_file)

    def wait_until(self, check, what: str):
        deadline = time.monotonic() + WAIT * 3
        while not check():
            assert time.monotonic() < deadline, f"not {what}:\n{self.logs()}"
            time.sleep(0.2)


@contextlib.contextmanager
def _container(root: Path, pems: dict[str, bytes], toml: str, **env: str):
    """Runs the supervisor in the frps base image on toml and the test's certificates; skips
    when Docker or the pinned base image is not at hand."""
    base, target, entrypoint = _image()
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", base], capture_output=True).returncode != 0:
        pytest.skip(f"no docker daemon or {base} not present locally")
    box = Container(docker, root, entrypoint)
    for directory in (box.frp, box.pki, box.state, box.active):
        directory.mkdir()
    (box.frp / "frps.toml").write_text(toml, encoding="utf-8")
    for name in PEMS:
        (box.pki / name).write_bytes(pems[name])
    run = [docker, "run", "-d", "--name", box.name, "--network", "none"]
    run += ["--user", f"{os.getuid()}:{os.getgid()}"]
    run += ["-v", f"{box.frp}:/etc/frp:ro", "-v", f"{box.pki}:{_FRPS_CERT_DIR}:ro"]
    run += ["-v", f"{box.state}:/var/lib/frps-state", "-v", f"{box.active}:/var/lib/frps-active"]
    for key, value in env.items():
        run += ["-e", f"{key}={value}"]
    run += ["-v", f"{SCRIPT}:{target}:ro", "--entrypoint", entrypoint[0], base, *entrypoint[1:]]
    try:
        subprocess.run(run, check=True, capture_output=True)
        yield box
    finally:
        subprocess.run([docker, "rm", "-f", box.name], capture_output=True)


STARTED_SUCCESSFULLY = "frps started successfully"


@pytest.mark.parametrize("case", ["generator output", "template", "key not on the list"])
def test_in_the_frps_image_frps_starts_only_from_a_checked_copy(tmp_path, pems, case):
    # Verbatim from the generator: the default paths of the supervisor are those of the image.
    extra = {**EXTRA, "sshTunnelGateway.bindPort": 7022} if case == "key not on the list" else EXTRA
    toml = generate_frps_toml(_cfg(**FULL, extra_config=json.dumps(extra)))
    if case == "template":
        toml = toml.replace(f'"{TOKEN}"', '"{{print}}{{print}}{{print}}"')
    accepted = case == "generator output"
    with _container(tmp_path, pems, toml) as box:
        box.wait_until(
            lambda: (
                box.status_file.exists() and (STARTED_SUCCESSFULLY in box.logs() or not accepted)
            ),
            "started",
        )
        logs = box.logs()
        status = box.read()
        if accepted:
            assert (status.state, status.reason) == ("running", "none"), logs
            assert "frps uses config file: /var/lib/frps-active/current/frps.toml" in logs
        else:
            assert (status.state, status.reason) == ("waiting", "verify_failed"), logs
            assert "frps started" not in logs
            assert list(box.active.iterdir()) == []


def test_in_the_frps_image_a_new_token_restarts_frps_and_term_ends_the_supervisor(tmp_path, pems):
    with _container(tmp_path, pems, generate_frps_toml(_cfg()), FRPS_POLL_SECONDS="1") as box:
        box.wait_until(
            lambda: box.logs().count(STARTED_SUCCESSFULLY) == 1 and box.read().state == "running",
            "frps up",
        )

        toml = generate_frps_toml(_cfg(auth_token=NEW_TOKEN))
        (box.frp / "frps.toml").write_text(toml, encoding="utf-8")
        box.wait_until(
            lambda: box.logs().count(STARTED_SUCCESSFULLY) == 2 and len(box.read().events) == 2,
            "frps restarted",
        )

        assert _events(box.read()) == [STARTED, (2, "applied", "none", True)], box.logs()
        assert subprocess.run(box.health, capture_output=True).returncode == 0
        subprocess.run([box.docker, "stop", "-t", "20", box.name], check=True, capture_output=True)
        inspect = [box.docker, "inspect", "--format", "{{.State.ExitCode}}", box.name]
        exit_code = subprocess.run(inspect, capture_output=True, text=True).stdout.strip()
        logs = box.logs()
        assert exit_code == "0", logs
        assert TOKEN not in logs and NEW_TOKEN not in logs
