# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frps supervisor (apps/frps/frps-supervisor.sh) starts frps only from a configuration that
passed every check: a non-empty frps.toml in the layout the server generates, with auth.method
token, a token of at least 16 characters, TLS forced and the three TLS paths pointing into the
PKI directory, webServer.port off the published bind port; the three files there, the
certificate files intact, the leaf not expired and matching its key; frps verify green. Input
files are read only as regular files of at most 1 MiB and within a time limit; a symlink,
anything else or a larger file is unreadable. A valid input is copied into current/ of the
working directory (the directory 0711, current/ 0750 and files 0640, root's and in the group of
frps: frps reads the copy under a user of its own and writes none of it, no other user reads
it) with its TLS paths pointed there, and frps runs from
current/, each time only while the copy is still the one the supervisor took over (one that
changed goes, with the event copy_changed) and has passed the check again. An invalid input
starts nothing, or frps from the last valid current/ (degraded); a missing frps.toml removes
current/. Every status file it writes (0644) passes the server's reader.

After the start it polls the input: a change that stayed the same for two polls is taken over
like at the start, restarting frps only for a new valid input, and one that keeps changing shows
as unstable; frps exiting on its own is restarted after a growing delay, three exits in a row
make a crash loop; TERM and INT stop frps and leave no process behind; `health` judges the
state. While frps runs from a copy with a webServer.port, every poll puts the proxy lists of
its dashboard, fetched over loopback under a user of their own (neither root nor that of frps)
with the credentials kept off every command line, into the state directory (proxy-<type>.json,
0644), each answer as it came; a failed request or an answer over 1 MiB leaves no file of its
type, and without frps or a webServer.port none is left.

The script runs under sh with a stub frps on PATH, without root and so with su-exec switched
off (FRPS_USER and FRPS_FETCH_USER empty; some tests put a stub su-exec in its place); a local
HTTP server stands in for the dashboard. Some tests run the frps image built from apps/frps,
with the capabilities and security options compose gives it, the real frps under its own user
and the requests to its dashboard under another; they skip when Docker or the pinned base image
is not at hand."""

import base64
import contextlib
import hashlib
import itertools
import json
import os
import pwd
import re
import shutil
import signal
import stat
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.modules.frp.config_generator import _FRPS_CERT_DIR, generate_frps_toml
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.supervisor_status import SupervisorStatus, read_supervisor_status

FRPS_DIR = Path(__file__).resolve().parents[2] / "frps"
SCRIPT = FRPS_DIR / "frps-supervisor.sh"
COMPOSE = FRPS_DIR.parents[1] / "docker-compose.yml"
TOKEN = "test-token-0123456789abcdef"
NEW_TOKEN = "next-token-fedcba9876543210"
PEMS = ("frps.crt", "frps.key", "ca.crt")
WAIT = 10.0
HEX64 = re.compile(r"[0-9a-f]{64}")
# The log line of a poll that sees an input it has not taken over yet.
CHANGED = "input changed"
# The most the supervisor reads of an input file.
INPUT_MAX = 1024 * 1024

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
        self.proc = root / "proc"
        self.log = root / "supervisor.log"
        self.procs: list[subprocess.Popen] = []
        self.supervisor: subprocess.Popen | None = None
        bin_dir = root / "bin"
        for directory in (self.config.parent, self.pki, self.stub, self.proc, bin_dir):
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
            # su-exec off: without root, frps and the requests to its dashboard run as the
            # test's user.
            "FRPS_USER": "",
            "FRPS_FETCH_USER": "",
            # Where the supervisor looks for processes of the user of frps: never the real
            # /proc, whose processes of the test's user it would KILL.
            "FRPS_PROC_ROOT": str(self.proc),
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
    box.config.chmod(0o600)
    for name in PEMS:
        (box.pki / name).chmod(0o755)
    # Modes the supervisor has to correct: the server reads the status under another UID, frps
    # the copy under one of its own through its group, and no one but frps lists the working
    # directory.
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
    assert _mode(box.active) == 0o711
    assert _mode(box.current) == 0o750
    assert {p.name: _mode(p) for p in box.current.iterdir()} == {
        name: 0o640 for name in (*PEMS, "frps.toml", "applied.sha256")
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


# Stands in for head or sha256sum: blocks on one file, as reading a FIFO swapped in after the
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
        for program in ("head", "sha256sum"):
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


def _pad(box: Box, name: str, size: int):
    """Fills an input file up to size bytes with empty lines, which leave it valid."""
    path = box.config if name == "frps.toml" else box.pki / name
    content = path.read_bytes()
    path.write_bytes(content + b"\n" * (size - len(content)))


@pytest.mark.parametrize("name", ["frps.toml", "frps.key", "ca.crt"])
@pytest.mark.parametrize("size", [INPUT_MAX, INPUT_MAX + 1], ids=["1 MiB", "a byte more"])
def test_an_input_file_over_1_mib_is_unreadable(box, name, size):
    box.write_input()
    _pad(box, name, size)

    doc = box.run(frps=size <= INPUT_MAX)

    status = box.read()
    if size <= INPUT_MAX:
        assert (status.state, status.reason) == ("running", "none")
        # Copied whole.
        expected = (box.config if name == "frps.toml" else box.pki / name).read_bytes()
        if name == "frps.toml":
            expected = expected.replace(f'"{box.pki}/'.encode(), f'"{box.current}/'.encode())
        assert (box.current / name).read_bytes() == expected
    else:
        assert (status.state, status.reason, status.events) == ("waiting", "input_unreadable", ())
        assert not box.frps_runs()
        assert list(box.active.iterdir()) == []
        assert doc["appliedHash"] is None and HEX64.fullmatch(doc["rejectedHash"])


def test_an_input_file_is_hashed_no_further_than_it_is_read(box):
    # A sparse file of 64 GiB: hashed whole, within a time limit of ten minutes, it would hold
    # up every poll for many seconds.
    box.env["FRPS_READ_SECONDS"] = "600"
    box.write_input()
    os.truncate(box.pki / "frps.key", 64 * 2**30)

    box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason) == ("waiting", "input_unreadable")


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


def _edit_copy(old: str, new: str):
    def change(box: Box):
        copy = box.current / "frps.toml"
        text = copy.read_text()
        assert text.count(old) == 1, old
        copy.write_text(text.replace(old, new))

    return change


# Changes to the copy in current/ after the supervisor took it over: one that passes the check
# of frps.toml, one that does not, and one of a PEM file, which that check does not read.
COPY_CHANGES = {
    "another token": _edit_copy(f'"{TOKEN}"', f'"{NEW_TOKEN}"'),
    "TLS not forced": _edit_copy("force = true", "force = false"),
    "ca.crt of another CA": lambda box: (box.current / "ca.crt").write_bytes(box.pems["other.crt"]),
}


def test_a_copy_from_an_earlier_run_that_fails_the_check_goes_for_an_invalid_input_too(box):
    box.write_input()
    box.run(frps=True)
    box.stop()
    # A new supervisor knows no hash of the copy it finds: the check alone decides on it.
    COPY_CHANGES["TLS not forced"](box)
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


COPY_CHANGED = ("copy_changed", "none", False)


@pytest.mark.parametrize("case", list(COPY_CHANGES))
def test_frps_that_exits_starts_again_from_the_input_never_from_a_changed_copy(box, case):
    _polling(box)
    box.wait_until(box.pids, "frps up")
    COPY_CHANGES[case](box)
    changed = _sha256((box.current / "frps.toml").read_text())

    os.kill(box.pids()[0], signal.SIGKILL)

    # The copy is no longer the one taken over: it goes before the restart, with an event,
    # and the input is taken over anew.
    status = box.wait_events(3)
    assert (status.state, status.reason) == ("running", "none")
    assert _events(status) == [STARTED, (2, *COPY_CHANGED), (3, "started", "none", False)]
    box.wait_until(lambda: len(box.pids()) == 2, "frps up again")
    assert box.calls() == _verify_then_run(box) * 2
    expected = box.config.read_text().replace(f'"{box.pki}/', f'"{box.current}/')
    assert (box.current / "frps.toml").read_text() == expected
    for name in PEMS:
        assert (box.current / name).read_bytes() == box.pems[name]
    assert box.ran() == [_sha256(expected)] * 2
    if case != "ca.crt of another CA":
        assert changed not in box.ran()
    assert _alive(box.pids()[-1])


def test_frps_that_exits_stays_down_with_a_changed_copy_and_an_invalid_input(box):
    _polling(box)
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})
    box.wait_state("degraded")
    # A change the check of frps.toml lets pass.
    COPY_CHANGES["another token"](box)
    changed = _sha256((box.current / "frps.toml").read_text())

    os.kill(box.pids()[0], signal.SIGKILL)

    # The copy goes, with an event; then as for an invalid input without a valid copy.
    status = box.wait_state("waiting")
    assert (status.reason, _events(status)) == (
        "cert_expired",
        [STARTED, (2, "rejected", "cert_expired", False), (3, *COPY_CHANGED)],
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


# Stands in for sleep: takes no TERM, as a child the supervisor has just forked does until it
# has dropped the trap of its shell, records its pid, then becomes the real sleep.
DEAF_SLEEP = """#!/bin/sh
trap '' TERM
echo $$ >> "$STUB_DIR/sleeps"
exec {real} "$@"
"""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT], ids=["TERM", "INT"])
def test_a_signal_ends_even_a_child_that_takes_no_term(box, sig):
    real = shutil.which("sleep")
    assert real, "sleep"
    (box.root / "bin" / "sleep").write_text(DEAF_SLEEP.format(real=real))
    (box.root / "bin" / "sleep").chmod(0o755)
    sleeps = box.stub / "sleeps"
    box.run(frps=False)
    # The pause before the hourly poll of Box, the one sleep of a supervisor without input.
    box.wait_until(lambda: sleeps.exists() and sleeps.read_text().strip(), "the pause")
    (pause,) = [int(pid) for pid in sleeps.read_text().split()]
    assert _alive(pause)

    box.supervisor.send_signal(sig)

    assert box.supervisor.wait(timeout=WAIT) == 0
    _wait_gone(box.supervisor.pid)


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


PROXY_TYPES = ("stcp", "https", "tcp", "udp")
DASHBOARD_USER = "admin-\u00fc"
# What a shell or curl's config would make something else of, were it not passed on as it is.
DASHBOARD_PASSWORD = f"pw:$HOME `id` # {uuid.uuid4().hex}"


def _answer(proxy_type: str) -> bytes:
    return f'{{"proxies": [{{"name": "srv1.{proxy_type}", "status": "online"}}]}}\n'.encode()


class Dashboard:
    """Stands in for the dashboard of frps on 127.0.0.1: answers GET /api/proxy/<type> with
    answers[type] (status, body, whether with a Content-Length), or, while hang is set, holds
    the request until the test ends. Notes every request with its Authorization header and,
    while it is open, every process with the password on its command line (leaks), next to
    the number of times a process asking the dashboard was seen at all (clients)."""

    def __init__(self):
        self.answers = {t: (200, _answer(t), True) for t in PROXY_TYPES}
        self.hang = False
        self.held = 0
        self.requests: list[tuple[str, str | None]] = []
        self.leaks: list[str] = []
        self.clients = 0
        self.release = threading.Event()
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                dashboard._serve(self)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _serve(self, request: BaseHTTPRequestHandler):
        self._scan()
        self.requests.append((request.path, request.headers.get("Authorization")))
        if self.hang:
            self.held += 1
            self.release.wait()
            return
        status, body, length = self.answers.get(request.path.rsplit("/", 1)[-1], (404, b"", True))
        request.send_response(status)
        if length:
            request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        # Without a length, the end of the connection ends the body (HTTP/1.0).
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            request.wfile.write(body)

    def _scan(self):
        password, asking = DASHBOARD_PASSWORD.encode(), f":{self.port}/api/proxy/".encode()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                line = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            if password in line:
                self.leaks.append(line.replace(b"\0", b" ").decode(errors="replace"))
            if asking in line:
                self.clients += 1

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def dashboard():
    dashboard = Dashboard()
    yield dashboard
    dashboard.close()


def _dashboard_toml(box: Box, dashboard: Dashboard) -> str:
    return _toml(
        box.pki,
        dashboard_port=dashboard.port,
        dashboard_user=DASHBOARD_USER,
        dashboard_password=DASHBOARD_PASSWORD,
    )


def _with_dashboard(box: Box, dashboard: Dashboard, **env: str):
    """A supervisor that polls every second, frps running with webServer on the dashboard;
    returns once the four proxy lists are there."""
    box.write_input(_dashboard_toml(box, dashboard))
    box.env.update({"FRPS_POLL_SECONDS": "1", **env})
    box.run(frps=True)
    box.wait_until(lambda: len(_proxy_files(box)) == len(PROXY_TYPES), "the proxy lists")


def _proxy_files(box: Box) -> dict[str, bytes]:
    """The proxy lists in the state directory, by type."""
    found = {}
    for proxy_type in PROXY_TYPES:
        with contextlib.suppress(FileNotFoundError):
            found[proxy_type] = (box.state / f"proxy-{proxy_type}.json").read_bytes()
    return found


def _state(box: Box, *, in_flight: bool = False) -> list[str]:
    """The files in the state directory; with in_flight, but for the temp files of requests
    under way, which a poll swaps in or removes once they are done."""
    names = sorted(p.name for p in box.state.iterdir())
    return [n for n in names if not (in_flight and n.startswith(".proxy-"))]


ALL_LISTS = sorted(["status.json", *(f"proxy-{t}.json" for t in PROXY_TYPES)])


def test_while_frps_runs_every_poll_puts_the_answers_of_its_dashboard_into_the_state(
    box, dashboard
):
    # As frps gave it, unparsed: this one is no JSON at all.
    dashboard.answers["udp"] = (200, b"no json \xff\n", True)

    _with_dashboard(box, dashboard)

    assert _proxy_files(box) == {t: dashboard.answers[t][1] for t in PROXY_TYPES}
    assert _state(box, in_flight=True) == ALL_LISTS
    assert {_mode(box.state / f"proxy-{t}.json") for t in PROXY_TYPES} == {0o644}
    credentials = base64.b64encode(f"{DASHBOARD_USER}:{DASHBOARD_PASSWORD}".encode()).decode()
    assert {path for path, _ in dashboard.requests} == {f"/api/proxy/{t}" for t in PROXY_TYPES}
    assert {auth for _, auth in dashboard.requests} == {f"Basic {credentials}"}

    # Every poll writes them anew, and a new answer shows.
    mtimes = {t: (box.state / f"proxy-{t}.json").stat().st_mtime_ns for t in PROXY_TYPES}
    dashboard.answers["stcp"] = (200, _answer("another"), True)
    box.wait_polls(2)
    box.wait_until(lambda: _proxy_files(box).get("stcp") == _answer("another"), "the new answer")
    for proxy_type in PROXY_TYPES:
        assert (box.state / f"proxy-{proxy_type}.json").stat().st_mtime_ns > mtimes[proxy_type]
    assert _state(box, in_flight=True) == ALL_LISTS


# Stands in for curl: records the arguments of each call, one line a call, then becomes the
# real curl, stdin and all. curl blanks the value of -u in its argv once it runs; the record is
# taken before that.
CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_DIR/curl"
exec {real} "$@"
"""


def test_no_process_carries_the_password_of_the_dashboard_on_its_command_line(box, dashboard):
    real = shutil.which("curl")
    assert real, "curl"
    (box.root / "bin" / "curl").write_text(CURL.format(real=real))
    (box.root / "bin" / "curl").chmod(0o755)

    _with_dashboard(box, dashboard)
    box.wait_until(lambda: len(dashboard.requests) >= 3 * len(PROXY_TYPES), "three polls")

    # Neither as it is nor as an Authorization header would carry it.
    credentials = base64.b64encode(f"{DASHBOARD_USER}:{DASHBOARD_PASSWORD}".encode()).decode()
    calls = (box.stub / "curl").read_text(encoding="utf-8").splitlines()
    assert len(calls) >= len(PROXY_TYPES)
    assert all(f"127.0.0.1:{dashboard.port}/api/proxy/" in call for call in calls), calls
    assert [c for c in calls if DASHBOARD_PASSWORD in c or credentials in c] == []
    # The credentials reached the dashboard all the same.
    assert {auth for _, auth in dashboard.requests} == {f"Basic {credentials}"}
    # Nor any other process while a request was open; looked for while curl waited for the
    # answer, and found curl then.
    assert dashboard.clients >= len(dashboard.requests) > 0
    assert dashboard.leaks == []


def test_without_webserver_port_no_proxy_list_is_left_not_even_one_of_an_earlier_run(box):
    box.state.mkdir()
    for proxy_type in PROXY_TYPES:
        (box.state / f"proxy-{proxy_type}.json").write_bytes(_answer(proxy_type))
    (box.state / ".proxy-tcp.json.tmp").write_bytes(b"cut short")

    _polling(box)
    assert _state(box) == ["status.json"]
    box.wait_polls(2)

    assert box.read().state == "running"
    assert _state(box) == ["status.json"]


def test_without_frps_its_dashboard_is_not_asked(box, dashboard):
    box.write_input(_dashboard_toml(box, dashboard), pems={"frps.crt": box.pems["expired.crt"]})
    box.env["FRPS_POLL_SECONDS"] = "1"

    box.run(frps=False)
    box.wait_polls(2)

    assert (box.read().state, box.read().reason) == ("waiting", "cert_expired")
    assert dashboard.requests == []
    assert _state(box) == ["status.json"]


def test_once_frps_stops_its_proxy_lists_go(box, dashboard):
    _with_dashboard(box, dashboard)

    box.config.unlink()
    box.wait_state("stopped")
    box.wait_until(lambda: not _proxy_files(box), "no proxy list")
    asked = len(dashboard.requests)
    box.wait_polls(2)

    assert len(dashboard.requests) == asked
    assert _state(box) == ["status.json"]


# An answer for stcp, and whether it is kept; without a length, the end of the connection
# ends the answer, so curl learns the size only as it reads it.
ANSWERS = {
    "1 MiB": ((200, b"x" * INPUT_MAX, True), True),
    "1 MiB without a length": ((200, b"x" * INPUT_MAX, False), True),
    "a byte more": ((200, b"x" * (INPUT_MAX + 1), True), False),
    "a byte more without a length": ((200, b"x" * (INPUT_MAX + 1), False), False),
    "HTTP 401": ((401, _answer("stcp"), True), False),
}


@pytest.mark.parametrize("case", list(ANSWERS))
def test_an_answer_over_1_mib_or_a_failed_request_leaves_no_file_of_its_type(box, dashboard, case):
    answer, kept = ANSWERS[case]
    _with_dashboard(box, dashboard)

    dashboard.answers["stcp"] = answer
    if kept:
        box.wait_until(lambda: _proxy_files(box).get("stcp") == answer[1], "the answer")
    else:
        box.wait_until(lambda: "stcp" not in _proxy_files(box), "no stcp list")
    box.wait_polls(2)

    files = _proxy_files(box)
    assert files.pop("stcp", None) == (answer[1] if kept else None)
    assert files == {t: _answer(t) for t in PROXY_TYPES if t != "stcp"}
    lists = ALL_LISTS if kept else [f for f in ALL_LISTS if "stcp" not in f]
    assert _state(box, in_flight=True) == lists


def test_a_dashboard_that_does_not_answer_leaves_no_file_and_the_polls_go_on(box, dashboard):
    _with_dashboard(box, dashboard, FRPS_READ_SECONDS="1")

    dashboard.hang = True
    box.wait_until(lambda: not _proxy_files(box), "no proxy list")
    # A poll a second, each held up for FRPS_READ_SECONDS at the most by its requests.
    held = dashboard.held
    box.wait_polls(3)

    assert dashboard.held >= held + len(PROXY_TYPES)
    assert box.read().state == "running"
    assert _state(box, in_flight=True) == ["status.json"]


def test_term_cuts_short_a_request_the_dashboard_does_not_answer(box, dashboard):
    # Requests far longer than frps gets to stop: only cut short do they let TERM end the
    # supervisor in time.
    _with_dashboard(box, dashboard, FRPS_READ_SECONDS="60", FRPS_STOP_SECONDS="5")
    dashboard.hang = True
    box.wait_until(lambda: dashboard.held >= len(PROXY_TYPES), "the requests of a poll held")

    box.supervisor.send_signal(signal.SIGTERM)

    assert box.supervisor.wait(timeout=5) == 0
    _wait_gone(box.supervisor.pid)
    assert _state(box) == ["status.json"]


SU_EXEC = """#!/bin/sh
# Stands in for su-exec: records the user and the command, and runs frps or curl as it is,
# nothing else, the user in SU_EXEC_USER.
printf '%s\\n' "$*" >> "$STUB_DIR/su-exec"
case $2 in frps | curl) ;; *) exit 0 ;; esac
SU_EXEC_USER=$1
export SU_EXEC_USER
shift
exec "$@"
"""


def _as_user(box: Box):
    """frps as the test's own user, through a stub su-exec; the processes of that user the
    supervisor sees are those in box.proc alone."""
    su_exec = box.root / "bin" / "su-exec"
    su_exec.write_text(SU_EXEC)
    su_exec.chmod(0o755)
    box.env["FRPS_USER"] = pwd.getpwuid(os.getuid()).pw_name


def _process(box: Box, pid: int, uid: int, state: str = "S (sleeping)"):
    """A process as box.proc shows it to the supervisor, without one behind it."""
    (box.proc / str(pid)).mkdir()
    (box.proc / str(pid) / "status").write_text(
        f"Name:\tsleep\nUmask:\t0022\nState:\t{state}\nTgid:\t{pid}\nPid:\t{pid}\n"
        f"PPid:\t1\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nGid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
    )


# No process ever has it (PID_MAX_LIMIT is 4194304): a KILL to it reaches nothing.
NO_PID = 99999999


def test_frps_runs_as_its_user_through_su_exec_and_verify_does_not(box):
    _as_user(box)
    user = box.env["FRPS_USER"]

    _polling(box)
    box.wait_until(box.pids, "frps up")
    os.kill(box.pids()[0], signal.SIGKILL)
    box.wait_until(lambda: len(box.pids()) == 2, "frps up again")
    # frps runs as the process su-exec became: TERM reaches it, nothing stays behind.
    box.supervisor.send_signal(signal.SIGTERM)
    assert box.supervisor.wait(timeout=WAIT) == 0
    _wait_gone(box.supervisor.pid)

    assert box.calls() == [*_verify_then_run(box), f"-c {box.current}/frps.toml"]
    # su-exec runs frps alone; no KILL is sent as the user of frps.
    run = f"{user} frps -c {box.current}/frps.toml"
    assert (box.stub / "su-exec").read_text().splitlines() == [run, run]


# Stands in for curl: records the user su-exec ran it as (none without su-exec), then becomes
# the real curl, stdin and all.
CURL_AS = """#!/bin/sh
printf '%s\\n' "${{SU_EXEC_USER:-none}}" >> "$STUB_DIR/curl"
exec {real} "$@"
"""


def test_every_request_to_the_dashboard_runs_as_its_user_through_su_exec(box, dashboard):
    su_exec = box.root / "bin" / "su-exec"
    su_exec.write_text(SU_EXEC)
    su_exec.chmod(0o755)
    real = shutil.which("curl")
    assert real, "curl"
    (box.root / "bin" / "curl").write_text(CURL_AS.format(real=real))
    (box.root / "bin" / "curl").chmod(0o755)
    user = pwd.getpwuid(os.getuid()).pw_name
    box.env["FRPS_FETCH_USER"] = user

    _with_dashboard(box, dashboard)
    box.wait_until(lambda: len(dashboard.requests) >= 2 * len(PROXY_TYPES), "two polls")

    # The four lists arrive as without su-exec, the credentials on stdin.
    assert _proxy_files(box) == {t: _answer(t) for t in PROXY_TYPES}
    credentials = base64.b64encode(f"{DASHBOARD_USER}:{DASHBOARD_PASSWORD}".encode()).decode()
    assert {auth for _, auth in dashboard.requests} == {f"Basic {credentials}"}
    # Each request through su-exec as the user, none around it, and no call with the password.
    calls = (box.stub / "su-exec").read_text(encoding="utf-8").splitlines()
    url = f" http://127.0.0.1:{dashboard.port}/api/proxy/"
    assert calls and all(c.startswith(f"{user} curl -q --config - ") for c in calls), calls
    assert all(url in c for c in calls), calls
    assert {c.rsplit(url, 1)[1] for c in calls} == set(PROXY_TYPES), calls
    assert [c for c in calls if DASHBOARD_PASSWORD in c or credentials in c] == []
    assert set((box.stub / "curl").read_text().split()) == {user}


def test_processes_of_the_frps_user_are_killed_before_frps_starts_and_after_it_ended(box):
    _as_user(box)
    uid = os.getuid()
    left = subprocess.Popen(["sleep", "600"], start_new_session=True)
    box.procs.append(left)
    (box.proc / str(left.pid)).symlink_to(f"/proc/{left.pid}")
    # Never counted: PID 1, a zombie, a process of another user.
    _process(box, 1, uid)
    _process(box, NO_PID - 1, uid, state="Z (zombie)")
    _process(box, NO_PID, uid + 1)

    _polling(box)

    assert left.wait(timeout=WAIT) == -signal.SIGKILL
    assert (box.read().state, box.read().reason) == ("running", "none")

    # The supervisor itself is never hit: after frps ended, it goes on to start it again.
    another = subprocess.Popen(["sleep", "600"], start_new_session=True)
    box.procs.append(another)
    for pid in (box.supervisor.pid, another.pid):
        (box.proc / str(pid)).symlink_to(f"/proc/{pid}")
    box.wait_until(box.pids, "frps up")
    os.kill(box.pids()[0], signal.SIGKILL)

    assert another.wait(timeout=WAIT) == -signal.SIGKILL
    box.wait_until(lambda: len(box.pids()) == 2, "frps up again")
    assert box.supervisor.poll() is None
    assert _events(box.read()) == [STARTED]


def test_a_process_of_the_frps_user_that_does_not_go_away_keeps_frps_from_starting(box):
    _as_user(box)
    box.env["FRPS_KILL_SECONDS"] = "1"
    _process(box, NO_PID, os.getuid())
    box.write_input()

    doc = box.run(frps=False)

    status = box.read()
    assert (status.state, status.reason) == ("waiting", "processes_left")
    assert _events(status) == [(1, "start_refused", "processes_left", False)]
    assert box.calls() == [f"verify -c {box.active}/next/frps.toml"]
    assert list(box.active.iterdir()) == []
    assert doc["appliedHash"] is None
    assert "processes of" in box._log()

    # Gone: the next input starts frps.
    (box.proc / str(NO_PID) / "status").unlink()
    (box.proc / str(NO_PID)).rmdir()
    box.stop()
    box.run(frps=True)
    assert (box.read().state, box.read().reason) == ("running", "none")


def test_a_process_of_the_frps_user_left_shows_over_an_invalid_input_and_its_last_valid_copy(box):
    _as_user(box)
    box.write_input()
    box.run(frps=True)
    box.stop()
    box.env["FRPS_KILL_SECONDS"] = "1"
    _process(box, NO_PID, os.getuid())
    box.write_input(pems={"frps.crt": box.pems["expired.crt"]})

    box.run(frps=False)

    # The status says why frps does not run from the last valid copy, the log what the input
    # breaks.
    status = box.read()
    assert (status.state, status.reason) == ("waiting", "processes_left")
    assert _events(status) == [(1, "start_refused", "processes_left", False)]
    assert not box.frps_runs()
    assert list(box.active.iterdir()) == []
    assert "configuration rejected: cert_expired" in box._log()


def test_a_process_of_the_frps_user_left_after_frps_ended_keeps_it_from_starting_again(box):
    _as_user(box)
    box.env["FRPS_KILL_SECONDS"] = "1"
    _polling(box)
    box.wait_until(box.pids, "frps up")
    _process(box, NO_PID, os.getuid())

    os.kill(box.pids()[0], signal.SIGKILL)

    status = box.wait_state("waiting", timeout=2 * WAIT)
    assert status.reason == "processes_left"
    assert _events(status) == [STARTED, (2, "start_refused", "processes_left", False)]
    box.wait_polls(2)
    assert box.runs() == 1
    assert list(box.active.iterdir()) == []


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
        ("FRPS_KILL_SECONDS", "0"),
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


@pytest.mark.parametrize("user", ["root", "no-such-user-for-frps"])
def test_a_frps_user_that_is_root_or_no_user_stops_the_supervisor(box, user):
    box.write_input()
    box.env["FRPS_USER"] = user

    result = box.once()

    assert result.returncode == 1 and "FRPS_USER" in result.stderr
    assert box.calls() == [] and not box.status_file.exists()


@pytest.mark.parametrize("user", ["root", "no-such-user-for-the-dashboard", "the user of frps"])
def test_a_fetch_user_that_is_root_no_user_or_the_user_of_frps_stops_the_supervisor(box, user):
    box.write_input()
    if user == "the user of frps":
        _as_user(box)
        user = box.env["FRPS_USER"]
    box.env["FRPS_FETCH_USER"] = user

    result = box.once()

    assert result.returncode == 1 and "FRPS_FETCH_USER" in result.stderr
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


def _frps_user() -> tuple[str, int]:
    """Name and UID of the user the image creates for frps."""
    dockerfile = (FRPS_DIR / "Dockerfile").read_text()
    found = re.search(r"\badduser\b.* -u (\d+) .*-G \w+ (\w+)", dockerfile)
    assert found, dockerfile
    return found[2], int(found[1])


def test_the_supervisor_runs_frps_as_the_user_the_image_creates_for_it():
    name, uid = _frps_user()
    assert uid != 0
    assert f'FRPS_USER="${{FRPS_USER-{name}}}"' in SCRIPT.read_text()


def _fetch_user() -> tuple[str, int]:
    """Name and UID of the user the requests to the dashboard run as by default, as the image
    creates it."""
    default = re.search(
        r'^FRPS_FETCH_USER="\$\{FRPS_FETCH_USER-(\S+)\}"$', SCRIPT.read_text(), re.M
    )
    assert default, "no default for FRPS_FETCH_USER"
    dockerfile = (FRPS_DIR / "Dockerfile").read_text()
    name = re.escape(default[1])
    found = re.search(rf"\badduser\b.* -u (\d+) -G {name} {name}(?: |$)", dockerfile, re.M)
    assert found, dockerfile
    return default[1], int(found[1])


def test_the_supervisor_asks_the_dashboard_as_a_user_of_its_own_the_image_creates():
    # _fetch_user finds it in a group of its own, too.
    _, uid = _fetch_user()
    assert uid not in (0, _frps_user()[1])


def _image() -> tuple[str, str, list[str]]:
    """Base image, the script's place in the image and the entrypoint, as in the Dockerfile."""
    dockerfile = (FRPS_DIR / "Dockerfile").read_text()
    base = re.search(r"^FROM (\S+)$", dockerfile, re.M)
    target = re.search(r"^COPY frps-supervisor\.sh (\S+)$", dockerfile, re.M)
    entrypoint = re.search(r"^ENTRYPOINT (\[.*\])$", dockerfile, re.M)
    assert base and target and entrypoint, dockerfile
    return base[1], target[1], json.loads(entrypoint[1])


def _compose_frps() -> dict:
    """The frps service of docker-compose.yml."""
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["frps"]


def _security_args(frps: dict) -> list[str]:
    """docker run arguments for the capabilities, security options and sysctls compose gives
    frps."""
    args = [arg for cap in frps["cap_drop"] for arg in ("--cap-drop", cap)]
    args += [arg for cap in frps["cap_add"] for arg in ("--cap-add", cap)]
    args += [arg for option in frps.get("security_opt", []) for arg in ("--security-opt", option)]
    sysctls = frps.get("sysctls", {}).items()
    args += [arg for key, value in sysctls for arg in ("--sysctl", f"{key}={value}")]
    return args


def _built_frps_image():
    """Builds the image from apps/frps, yields (docker, tag) and removes the image again; skips
    when Docker or the pinned base image is not at hand."""
    base, _, _ = _image()
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", base], capture_output=True).returncode != 0:
        pytest.skip(f"no docker daemon or {base} not present locally")
    tag = f"adminhelper-test/frps-supervisor:{uuid.uuid4().hex[:12]}"
    build = subprocess.run(
        [docker, "build", "-q", "-t", tag, str(FRPS_DIR)], capture_output=True, text=True
    )
    assert build.returncode == 0, build.stderr
    try:
        yield docker, tag
    finally:
        subprocess.run([docker, "image", "rm", "-f", tag], capture_output=True)


@pytest.fixture(scope="module")
def frps_image():
    yield from _built_frps_image()


STATE_DIR = "/var/lib/frps-state"
ACTIVE_DIR = "/var/lib/frps-active"
# Name, state, pid and UID of every process, one line each.
_PROCESSES = r"""for status in /proc/[0-9]*/status; do
    awk '/^(Name|State|Pid|Uid):/ { printf "%s ", $2 } END { print "" }' "$status" 2>/dev/null
done"""


class Container:
    """A container of the frps image as compose runs it (capabilities, security options,
    sysctls): its input bind-mounted read-only from the test's directory, the state and the
    working directory in volumes of its own."""

    def __init__(self, docker: str, root: Path, entrypoint: list[str]):
        self.docker = docker
        self.name = f"frps-supervisor-test-{uuid.uuid4().hex[:12]}"
        self.frp, self.pki, self.probe = root / "frp", root / "pki", root / "probe"
        self.status_copy = root / "status.json"
        self.volumes = {STATE_DIR: f"{self.name}-state", ACTIVE_DIR: f"{self.name}-active"}
        self.health = [docker, "exec", self.name, *entrypoint, "health"]

    def exec(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.docker, "exec", self.name, *args], capture_output=True, text=True
        )

    def logs(self) -> str:
        return subprocess.run(
            [self.docker, "logs", self.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ).stdout

    def read(self) -> SupervisorStatus:
        """The status file through the server's reader; missing while there is none."""
        result = self.exec("cat", f"{STATE_DIR}/status.json")
        if result.returncode != 0:
            return SupervisorStatus(state="missing")
        self.status_copy.write_text(result.stdout)
        return read_supervisor_status(self.status_copy)

    def frps(self) -> dict[str, str]:
        """Identity and capabilities of the running frps, from its /proc status."""
        result = self.exec("sh", "-c", 'cat "/proc/$(pidof frps)/status"')
        assert result.returncode == 0, result.stderr
        fields = dict(line.split(":", 1) for line in result.stdout.splitlines() if ":" in line)
        keys = ("Uid", "Gid", "CapPrm", "CapEff", "NoNewPrivs")
        return {key: " ".join(fields[key].split()) for key in keys}

    def processes(self, uid: int) -> list[tuple[str, str, int]]:
        """(name, state, pid) of every process of uid, zombies included, from /proc: busybox
        ps leaves out those it cannot read."""
        result = self.exec("sh", "-c", _PROCESSES)
        found = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 4 and fields[3] == str(uid):
                name, state, pid, _ = fields
                found.append((name, state, int(pid)))
        return sorted(found)

    def stop(self) -> str:
        """docker stop within the grace period compose gives frps; returns the exit code."""
        grace = _compose_frps()["stop_grace_period"].removesuffix("s")
        subprocess.run(
            [self.docker, "stop", "-t", grace, self.name], check=True, capture_output=True
        )
        inspect = [self.docker, "inspect", "--format", "{{.State.ExitCode}}", self.name]
        return subprocess.run(inspect, capture_output=True, text=True).stdout.strip()

    def wait_until(self, check, what: str):
        deadline = time.monotonic() + WAIT * 3
        while not check():
            assert time.monotonic() < deadline, f"not {what}:\n{self.logs()}"
            time.sleep(0.2)


@contextlib.contextmanager
def _container(image, root: Path, pems, toml: str, *, frps_bin: str | None = None, **env: str):
    """Runs the frps image (frps_image) on toml and the test's certificates. frps_bin, a
    script, stands in for frps."""
    docker, tag = image
    _, _, entrypoint = _image()
    box = Container(docker, root, entrypoint)
    for directory in (box.frp, box.pki):
        directory.mkdir()
    (box.frp / "frps.toml").write_text(toml, encoding="utf-8")
    for name in PEMS:
        (box.pki / name).write_bytes(pems[name])
    run = [docker, "run", "-d", "--name", box.name, "--network", "none"]
    run += _security_args(_compose_frps())
    run += ["-v", f"{box.frp}:/etc/frp:ro", "-v", f"{box.pki}:{_FRPS_CERT_DIR}:ro"]
    for target, volume in box.volumes.items():
        run += ["--mount", f"type=volume,src={volume},dst={target}"]
    if frps_bin is not None:
        # Run under the UID of frps, which has to read it.
        box.probe.mkdir()
        box.probe.chmod(0o755)
        (box.probe / "frps").write_text(frps_bin)
        (box.probe / "frps").chmod(0o755)
        run += ["-v", f"{box.probe}:/probe:ro", "-e", "FRPS_BIN=/probe/frps"]
    for key, value in env.items():
        run += ["-e", f"{key}={value}"]
    run.append(tag)
    try:
        subprocess.run(run, check=True, capture_output=True)
        yield box
    finally:
        subprocess.run([docker, "rm", "-f", box.name], capture_output=True)
        for volume in box.volumes.values():
            subprocess.run([docker, "volume", "rm", volume], capture_output=True)


STARTED_SUCCESSFULLY = "frps started successfully"


@pytest.mark.parametrize("case", ["generator output", "template", "key not on the list"])
def test_in_the_frps_image_frps_starts_only_from_a_checked_copy(tmp_path, pems, frps_image, case):
    # Verbatim from the generator: the default paths of the supervisor are those of the image.
    extra = {**EXTRA, "sshTunnelGateway.bindPort": 7022} if case == "key not on the list" else EXTRA
    toml = generate_frps_toml(_cfg(**FULL, extra_config=json.dumps(extra)))
    if case == "template":
        toml = toml.replace(f'"{TOKEN}"', '"{{print}}{{print}}{{print}}"')
    accepted = case == "generator output"
    with _container(frps_image, tmp_path, pems, toml) as box:
        box.wait_until(
            lambda: (
                box.read().state != "missing"
                and (STARTED_SUCCESSFULLY in box.logs() or not accepted)
            ),
            "started",
        )
        logs = box.logs()
        status = box.read()
        if accepted:
            assert (status.state, status.reason) == ("running", "none"), logs
            assert f"frps uses config file: {ACTIVE_DIR}/current/frps.toml" in logs
        else:
            assert (status.state, status.reason) == ("waiting", "verify_failed"), logs
            assert "frps started" not in logs
            assert box.exec("ls", "-A", ACTIVE_DIR).stdout == ""


# Stands in for frps: verify goes to frps as it is; a run first notes what it may do with the
# identity the supervisor gives frps, then becomes frps.
PROBE = r"""#!/bin/sh
if [ "$1" = verify ]; then exec frps "$@"; fi
try() {
    if sh -c "$2" >/dev/null 2>&1; then echo "$1: yes"; else echo "$1: no"; fi
}
current=/var/lib/frps-active/current
{
    echo "uid: $(id -u)"
    awk '/^(CapEff|NoNewPrivs):/ { print $1, $2 }' /proc/self/status
    for name in frps.toml frps.crt frps.key ca.crt; do
        try "read $name" "cat $current/$name"
    done
    for file in $current/frps.toml $current/frps.crt $current/frps.key $current/ca.crt \
        $current/applied.sha256 /var/lib/frps-state/status.json \
        /usr/local/bin/frps-supervisor.sh; do
        try "write $file" ": >> $file"
    done
    for dir in $current /var/lib/frps-active /var/lib/frps-state /usr/local/bin; do
        try "create in $dir" ": > $dir/probe"
    done
    try "signal the supervisor" "kill -0 1"
} > /tmp/probe.new
mv /tmp/probe.new /tmp/probe
exec frps "$@"
"""


def test_in_the_frps_image_frps_runs_as_its_user_and_changes_nothing_it_runs_from(
    tmp_path, pems, frps_image
):
    _, uid = _frps_user()
    _, script, _ = _image()
    with _container(frps_image, tmp_path, pems, generate_frps_toml(_cfg()), frps_bin=PROBE) as box:
        box.wait_until(
            lambda: STARTED_SUCCESSFULLY in box.logs() and box.read().state == "running",
            "frps up",
        )

        probe = box.exec("cat", "/tmp/probe")
        assert probe.returncode == 0, box.logs()
        current = f"{ACTIVE_DIR}/current"
        files = [f"{current}/{name}" for name in ("frps.toml", *PEMS, "applied.sha256")]
        files += [f"{STATE_DIR}/status.json", script]
        dirs = [current, ACTIVE_DIR, STATE_DIR, str(Path(script).parent)]
        # It reads the copy, the key included, and writes none of it, nor the status or the
        # supervisor, and cannot signal the supervisor.
        assert dict(line.split(": ", 1) for line in probe.stdout.splitlines()) == {
            "uid": str(uid),
            "CapEff": "0" * 16,
            "NoNewPrivs": "1",
            **{f"read {name}": "yes" for name in ("frps.toml", *PEMS)},
            **{f"write {file}": "no" for file in files},
            **{f"create in {directory}": "no" for directory in dirs},
            "signal the supervisor": "no",
        }
        # The process the probe became: frps.
        assert box.frps() == {
            "Uid": f"{uid} {uid} {uid} {uid}",
            "Gid": f"{uid} {uid} {uid} {uid}",
            "CapPrm": "0" * 16,
            "CapEff": "0" * 16,
            "NoNewPrivs": "1",
        }
        # No program in the image leads back to root.
        found = box.exec("find", "/", "-xdev", "-type", "f", "-perm", "/6000")
        assert (found.returncode, found.stdout) == (0, "")


def test_in_the_frps_image_a_new_token_restarts_frps_and_term_ends_the_supervisor(
    tmp_path, pems, frps_image
):
    toml = generate_frps_toml(_cfg())
    with _container(frps_image, tmp_path, pems, toml, FRPS_POLL_SECONDS="1") as box:
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
        exit_code = box.stop()
        logs = box.logs()
        assert exit_code == "0", logs
        assert TOKEN not in logs and NEW_TOKEN not in logs


# Stands in for frps: verify goes to frps as it is; a run notes its UID and ignores TERM.
STUBBORN = """#!/bin/sh
if [ "$1" = verify ]; then exec frps "$@"; fi
id -u >> /tmp/runs
trap '' TERM
exec sleep 600
"""


def test_in_the_frps_image_frps_that_ignores_term_is_killed_across_its_uid(
    tmp_path, pems, frps_image
):
    _, uid = _frps_user()
    toml = generate_frps_toml(_cfg())
    env = {"FRPS_POLL_SECONDS": "1", "FRPS_STOP_SECONDS": "1"}
    with _container(frps_image, tmp_path, pems, toml, frps_bin=STUBBORN, **env) as box:
        box.wait_until(lambda: box.read().state == "running", "frps up")

        # A change restarts frps: TERM, then KILL.
        toml = generate_frps_toml(_cfg(auth_token=NEW_TOKEN))
        (box.frp / "frps.toml").write_text(toml, encoding="utf-8")
        box.wait_until(lambda: len(box.read().events) == 2, "frps restarted")
        assert _events(box.read()) == [STARTED, (2, "applied", "none", True)], box.logs()
        box.wait_until(
            lambda: box.exec("cat", "/tmp/runs").stdout.split() == [str(uid)] * 2, "frps again"
        )
        assert box.logs().count("killing it") == 1

        # So does docker stop.
        exit_code = box.stop()
        logs = box.logs()
        assert exit_code == "0", logs
        assert logs.count("killing it") == 2


# Stands in for frps: verify goes to frps as it is; the first run leaves a process behind under
# the UID of frps, then becomes frps.
FORKS = """#!/bin/sh
if [ "$1" = verify ]; then exec frps "$@"; fi
if [ ! -e /tmp/forked ]; then
    : > /tmp/forked
    sleep 600 &
fi
exec frps "$@"
"""


@pytest.mark.parametrize("end", ["new token", "frps exits"])
def test_in_the_frps_image_no_process_of_frps_outlives_it(tmp_path, pems, frps_image, end):
    _, uid = _frps_user()
    toml = generate_frps_toml(_cfg())
    env = {"FRPS_POLL_SECONDS": "1"}
    with _container(frps_image, tmp_path, pems, toml, frps_bin=FORKS, **env) as box:
        box.wait_until(
            lambda: box.logs().count(STARTED_SUCCESSFULLY) == 1 and box.read().state == "running",
            "frps up",
        )
        box.wait_until(lambda: len(box.processes(uid)) == 2, "the process frps left")
        (old,) = [pid for name, _, pid in box.processes(uid) if name == "frps"]

        if end == "new token":
            toml = generate_frps_toml(_cfg(auth_token=NEW_TOKEN))
            (box.frp / "frps.toml").write_text(toml, encoding="utf-8")
        else:
            box.exec("kill", "-KILL", str(old))
        box.wait_until(lambda: box.logs().count(STARTED_SUCCESSFULLY) == 2, "frps again")

        _wait_frps_alone(box, uid, but_not=old)


def _wait_frps_alone(box: Container, uid: int, but_not: int | None = None) -> list:
    """Waits until the one process of uid is a frps (other than but_not): no other process,
    not even a zombie. Returns the processes of uid."""
    seen = []

    def alone() -> bool:
        seen[:] = box.processes(uid)
        names = [name for name, _, _ in seen]
        return names == ["frps"] and seen[0][1] != "Z" and seen[0][2] != but_not

    try:
        box.wait_until(alone, "the new frps alone")
    except AssertionError as failed:
        raise AssertionError(f"processes of {uid}: {seen}\n{failed}") from None
    return seen


# Stands in for frps: verify goes to frps as it is; the first run leaves a process behind under
# the UID of frps that fights its end (CHILD), then becomes frps.
FEND = """#!/bin/sh
if [ "$1" = verify ]; then exec frps "$@"; fi
if [ ! -e /tmp/forked ]; then
    : > /tmp/forked
    sh -c 'CHILD' &
fi
exec frps "$@"
"""
FENDS = {
    # Every process of its UID named kill or su-exec, as soon as it shows up.
    "kills kill and su-exec": "while :; do for d in /proc/[0-9]*; do"
    ' { read -r c < "$d/comm"; } 2>/dev/null || continue;'
    ' case $c in kill | su-exec) kill -9 "${d#/proc/}" 2>/dev/null ;; esac;'
    " done; done",
    # Every process of its UID but itself, frps included.
    "kills its whole UID": "while :; do kill -9 -1 2>/dev/null; done",
}
# A UID of another service, in the container through docker exec.
OTHER_UID = 10001


@pytest.mark.parametrize("child", list(FENDS))
def test_in_the_frps_image_a_process_frps_left_cannot_fend_off_its_end(
    tmp_path, pems, frps_image, child
):
    _, uid = _frps_user()
    toml = generate_frps_toml(_cfg())
    frps_bin = FEND.replace("CHILD", FENDS[child])
    env = {"FRPS_POLL_SECONDS": "1"}
    with _container(frps_image, tmp_path, pems, toml, frps_bin=frps_bin, **env) as box:
        box.wait_until(lambda: box.read().state == "running", "frps up")
        exec_other = [box.docker, "exec", "-d", "-u", str(OTHER_UID), box.name, "sleep", "600"]
        subprocess.run(exec_other, check=True, capture_output=True)

        toml = generate_frps_toml(_cfg(auth_token=NEW_TOKEN))
        (box.frp / "frps.toml").write_text(toml, encoding="utf-8")
        box.wait_until(
            lambda: "applied" in [event.event for event in box.read().events], "new token"
        )

        # Of the user of frps, the frps started last alone is left; another user's process
        # stays.
        (frps,) = _wait_frps_alone(box, uid)
        started = re.findall(r"frps started from \S+ \(pid (\d+)\)", box.logs())
        assert frps[2] == int(started[-1])
        assert box.read().state == "running"
        assert [name for name, _, _ in box.processes(OTHER_UID)] == ["sleep"]


def test_in_the_frps_image_the_supervisor_does_not_run_frps_as_root(frps_image):
    docker, tag = frps_image
    name = f"frps-supervisor-test-{uuid.uuid4().hex[:12]}"
    run = [docker, "run", "--name", name, "--network", "none", *_security_args(_compose_frps())]
    run += ["-e", "FRPS_USER=", tag]
    try:
        result = subprocess.run(run, capture_output=True, text=True, timeout=WAIT * 3)
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)

    assert result.returncode == 1 and "FRPS_USER" in result.stderr, result.stderr


def test_in_the_frps_image_the_supervisor_does_not_ask_the_dashboard_as_root(frps_image):
    docker, tag = frps_image
    name = f"frps-supervisor-test-{uuid.uuid4().hex[:12]}"
    run = [docker, "run", "--name", name, "--network", "none", *_security_args(_compose_frps())]
    run += ["-e", "FRPS_FETCH_USER=", tag]
    try:
        result = subprocess.run(run, capture_output=True, text=True, timeout=WAIT * 3)
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)

    assert result.returncode == 1 and "FRPS_FETCH_USER" in result.stderr, result.stderr


# Stands in for frps: verify goes to frps as it is; a run takes the connections to the port of
# its dashboard (7500, as in the test below), answers none of them and drops what it reads.
SILENT = """#!/bin/sh
if [ "$1" = verify ]; then exec frps "$@"; fi
exec nc -dlk 127.0.0.1 7500 > /dev/null
"""


def test_in_the_frps_image_the_supervisor_asks_the_dashboard_as_its_user(
    tmp_path, pems, frps_image
):
    _, uid = _fetch_user()
    config = _cfg(
        dashboard_port=7500, dashboard_user=DASHBOARD_USER, dashboard_password=DASHBOARD_PASSWORD
    )
    # Requests held open longer than the grace period compose gives frps.
    env = {"FRPS_POLL_SECONDS": "1", "FRPS_READ_SECONDS": "60"}
    toml = generate_frps_toml(config)
    with _container(frps_image, tmp_path, pems, toml, frps_bin=SILENT, **env) as box:
        # The requests of a poll, all of them under way: curl as the user of the requests, none
        # as root.
        box.wait_until(
            lambda: [p[0] for p in box.processes(uid)] == ["curl"] * len(PROXY_TYPES),
            "the requests of a poll as their user",
        )

        assert [process for process in box.processes(0) if process[0] == "curl"] == []
        # TERM ends them as before, and with them the supervisor within the grace period.
        assert box.stop() == "0", box.logs()


def test_in_the_frps_image_the_copy_is_open_to_frps_alone_not_to_the_user_of_the_requests(
    tmp_path, pems, frps_image
):
    frps, _ = _frps_user()
    fetch, fetch_uid = _fetch_user()
    with _container(frps_image, tmp_path, pems, generate_frps_toml(_cfg())) as box:
        box.wait_until(
            lambda: STARTED_SUCCESSFULLY in box.logs() and box.read().state == "running",
            "frps up",
        )

        current = f"{ACTIVE_DIR}/current"
        files = [f"{current}/{name}" for name in ("frps.toml", *PEMS, "applied.sha256")]
        # root's and in the group of frps; nothing for anyone else.
        group = box.exec("id", "-gn", frps).stdout.strip()
        modes = box.exec("stat", "-c", "%a %U %G %n", current, *files)
        assert modes.stdout.splitlines() == [
            f"750 root {group} {current}",
            *(f"640 root {group} {file}" for file in files),
        ], modes.stderr

        def reads(user: str) -> dict[str, bool]:
            """What user reads of the copy, switched to by su-exec as the supervisor does."""
            tries = {current: ["ls", current], **{file: ["cat", file] for file in files}}
            return {
                path: box.exec("su-exec", user, *args).returncode == 0
                for path, args in tries.items()
            }

        assert reads(frps) == dict.fromkeys([current, *files], True)
        # The switch itself works: what fails is the reading.
        assert box.exec("su-exec", fetch, "id", "-u").stdout.strip() == str(fetch_uid)
        assert reads(fetch) == dict.fromkeys([current, *files], False)


def test_in_the_frps_image_the_supervisor_puts_the_proxy_lists_of_frps_into_the_state(
    tmp_path, pems, frps_image
):
    config = _cfg(
        dashboard_port=7500, dashboard_user=DASHBOARD_USER, dashboard_password=DASHBOARD_PASSWORD
    )
    lists = [f"{STATE_DIR}/proxy-{t}.json" for t in PROXY_TYPES]
    with _container(
        frps_image, tmp_path, pems, generate_frps_toml(config), FRPS_POLL_SECONDS="1"
    ) as box:
        box.wait_until(lambda: box.exec("cat", *lists).returncode == 0, "the proxy lists")

        # curl of the image, the dashboard of the real frps over loopback, its credentials.
        for path in lists:
            result = box.exec("cat", path)
            assert json.loads(result.stdout) == {"proxies": []}, result.stdout
        modes = box.exec("stat", "-c", "%a %u", *lists).stdout.split("\n")
        assert modes[: len(lists)] == ["644 0"] * len(lists)
        assert DASHBOARD_PASSWORD not in box.logs()
