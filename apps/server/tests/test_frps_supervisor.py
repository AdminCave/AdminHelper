# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The frps supervisor (apps/frps/frps-supervisor.sh) starts frps only from a configuration that
passed every check: a non-empty frps.toml in the layout the server generates, with auth.method
token, a token of at least 16 characters, TLS forced and the three TLS paths pointing into the
PKI directory; the three files there, the certificate files intact, the leaf not expired and
matching its key; frps verify green. A valid input is copied into current/ of the working
directory with its TLS paths pointed there, and frps runs from current/. An invalid input starts
nothing, or frps from the last valid current/ (degraded); a missing frps.toml removes current/.
Every status file it writes passes the server's reader.

The script runs under sh with a stub frps on PATH. One test runs it in the frps image with the
real frps; it skips when Docker or the pinned base image is not at hand."""

import json
import os
import re
import shutil
import signal
import stat
import subprocess
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
PEMS = ("frps.crt", "frps.key", "ca.crt")
WAIT = 10.0
HEX64 = re.compile(r"[0-9a-f]{64}")

STUB = """#!/bin/sh
# Stands in for frps: records every call; verify keeps a copy of the file it was given and fails
# while $STUB_DIR/verify-fails exists; a run stays up until it is killed.
printf '%s\\n' "$*" >> "$STUB_DIR/calls"
if [ "$1" = verify ]; then
    cp "$3" "$STUB_DIR/verified.toml"
    [ ! -e "$STUB_DIR/verify-fails" ]
    exit
fi
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

    def calls(self) -> list[str]:
        calls = self.stub / "calls"
        return calls.read_text().splitlines() if calls.exists() else []

    def frps_runs(self) -> bool:
        return any(call.startswith("-c ") for call in self.calls())

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
    assert all(_mode(p) & 0o077 == 0 for p in box.current.iterdir())
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


@pytest.mark.parametrize("case", ["generator output", "template", "key not on the list"])
def test_in_the_frps_image_frps_starts_only_from_a_checked_copy(tmp_path, pems, case):
    base, target, entrypoint = _image()
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not available")
    if subprocess.run([docker, "image", "inspect", base], capture_output=True).returncode != 0:
        pytest.skip(f"no docker daemon or {base} not present locally")
    frp, pki, state, active = (tmp_path / name for name in ("frp", "pki", "state", "active"))
    for directory in (frp, pki, state, active):
        directory.mkdir()
    # Verbatim from the generator: the default paths of the supervisor are those of the image.
    extra = {**EXTRA, "sshTunnelGateway.bindPort": 7022} if case == "key not on the list" else EXTRA
    toml = generate_frps_toml(_cfg(**FULL, extra_config=json.dumps(extra)))
    if case == "template":
        toml = toml.replace(f'"{TOKEN}"', '"{{print}}{{print}}{{print}}"')
    accepted = case == "generator output"
    (frp / "frps.toml").write_text(toml, encoding="utf-8")
    for name in PEMS:
        (pki / name).write_bytes(pems[name])
    container = f"frps-supervisor-test-{uuid.uuid4().hex[:12]}"
    run = [docker, "run", "-d", "--name", container, "--network", "none"]
    run += ["--user", f"{os.getuid()}:{os.getgid()}"]
    run += ["-v", f"{frp}:/etc/frp:ro", "-v", f"{pki}:{_FRPS_CERT_DIR}:ro"]
    run += ["-v", f"{state}:/var/lib/frps-state", "-v", f"{active}:/var/lib/frps-active"]
    run += ["-v", f"{SCRIPT}:{target}:ro", "--entrypoint", entrypoint[0], base, *entrypoint[1:]]
    try:
        subprocess.run(run, check=True, capture_output=True)
        deadline = time.monotonic() + WAIT * 3
        while True:
            logs = subprocess.run(
                [docker, "logs", container],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            ).stdout
            started = "frps started successfully" in logs
            if (state / "status.json").exists() and (started or not accepted):
                break
            assert time.monotonic() < deadline, logs
            time.sleep(0.2)
        status = read_supervisor_status(state / "status.json")
        if accepted:
            assert (status.state, status.reason) == ("running", "none"), logs
            assert "frps uses config file: /var/lib/frps-active/current/frps.toml" in logs
        else:
            assert (status.state, status.reason) == ("waiting", "verify_failed"), logs
            assert "frps started" not in logs
            assert list(active.iterdir()) == []
    finally:
        subprocess.run([docker, "rm", "-f", container], capture_output=True)
