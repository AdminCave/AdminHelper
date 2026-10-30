# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The operator CLI of the ca-issuer (R-0667): `status` shows root, current and retired
intermediates with their end, its exit code says whether one needs attention;
`rotate-intermediates` takes the root passphrase from the secret file, the terminal or
stdin and changes nothing when it has none or a wrong one."""

import datetime
import getpass
import hashlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID

from app import cli, pki, rotation, storage

PW = b"pw"


@pytest.fixture
def pki_dir(monkeypatch, tmp_path):
    """A booted hierarchy under CA_DATA_DIR=tmp_path, no passphrase in the environment."""
    monkeypatch.setenv("CA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", "")
    monkeypatch.setenv("CA_ROOT_PASSPHRASE", "")
    d = tmp_path / "pki"
    storage.ensure_hierarchy(d, PW)
    return d


def _snapshot(d: Path) -> dict[str, str]:
    """sha256 of every file in d but the lock file, which a rotation leaves."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in d.iterdir()
        if p.name != rotation.LOCK_NAME
    }


def _stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))  # isatty() is False


def _cert_with_days_left(monkeypatch, role: str, days: int):
    """A root ("root") or an intermediate of scope `role` that has `days` left (negative:
    expired that long ago). The CLI checks the issuer of retired entries only, so a
    throwaway root stands in as the issuer of the intermediate."""
    lifetime = pki.VALIDITY_DAYS_ROOT if role == "root" else pki.VALIDITY_DAYS_INTERMEDIATE
    then = pki._now() - datetime.timedelta(days=lifetime - days)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        root_cert, root_key = pki.build_root_ca()
        if role == "root":
            return root_cert
        return pki.build_intermediate_ca(role, root_cert, root_key)[0]


def _root_of(d: Path) -> x509.Certificate:
    return pki.cert_from_pem((d / "root.crt").read_bytes())


def _retired_with_days_left(d: Path, scope: str, days: int) -> x509.Certificate:
    """An intermediate of `scope` under the root of d, as pki.build_intermediate_ca makes
    one, that has `days` left (negative: expired that long ago). Built by hand: pki issues
    nothing before its issuer's start, and the root of d is from today."""
    root_key = pki.key_from_pem((d / "root.key.enc").read_bytes(), PW)
    now = pki._now()
    cn = f"AdminHelper {scope.capitalize()} Intermediate"
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .issuer_name(_root_of(d).subject)
        .public_key(pki.generate_key().public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=pki.VALIDITY_DAYS_INTERMEDIATE - days))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(root_key, hashes.SHA256())
    )


def test_status_of_a_fresh_hierarchy(pki_dir, capsys):
    rc = cli.main(["status"])

    lines = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert len(lines) == 1 + len(pki.SCOPES)  # root and the current ones, nothing retired
    certs = [pki.cert_from_pem((pki_dir / "root.crt").read_bytes())] + [
        pki.cert_from_pem((pki_dir / f"{scope}.crt").read_bytes()) for scope in pki.SCOPES
    ]
    for role, line, cert in zip(("root", *pki.SCOPES), lines, certs, strict=True):
        assert line.split()[0] == role
        assert pki.read_identity(cert)[0] in line
        assert cert.not_valid_after_utc.isoformat() in line
        assert "retired" not in line


@pytest.mark.parametrize("role", ["root", "access"])
@pytest.mark.parametrize(("days", "code"), [(30, 1), (-1, 3)])
def test_status_exit_code_follows_the_root_and_the_current_intermediates(
    monkeypatch, pki_dir, capsys, role, days, code
):
    cert = _cert_with_days_left(monkeypatch, role, days)
    name = "root.crt" if role == "root" else f"{role}.crt"
    (pki_dir / name).write_bytes(pki.cert_to_pem(cert))

    assert cli.main(["status"]) == code
    assert pki.read_identity(cert)[0] in capsys.readouterr().out


@pytest.mark.parametrize(
    "name", ["root.crt", "internal.crt", "tunnel-retired.pem"], ids=["root", "current", "retired"]
)
def test_status_of_an_unreadable_certificate_is_3(pki_dir, capsys, name):
    (pki_dir / name).write_bytes(b"-----BEGIN CERTIFICATE-----\nnot a certificate\n")

    assert cli.main(["status"]) == 3
    assert "unreadable" in capsys.readouterr().out


def test_status_of_a_missing_root_is_3(pki_dir, capsys):
    (pki_dir / "root.crt").unlink()

    assert cli.main(["status"]) == 3
    assert "unreadable" in capsys.readouterr().out


def test_status_lists_retired_ones_without_judging_them(monkeypatch, pki_dir, capsys):
    # A retired intermediate runs out by design; an expired one is only dropped at the next boot.
    valid = _retired_with_days_left(pki_dir, "access", 10)
    expired = _retired_with_days_left(pki_dir, "access", -1)
    (pki_dir / "access-retired.pem").write_bytes(pki.chain_pem(valid, expired))

    rc = cli.main(["status"])

    retired = [line for line in capsys.readouterr().out.splitlines() if "(retired)" in line]
    assert rc == 0
    assert len(retired) == 2
    assert all(line.startswith("access (retired)") for line in retired)
    assert not any("SKIPPED" in line for line in retired)


def test_status_marks_a_retired_entry_the_boot_skips(pki_dir, capsys):
    # The boot skips it with a WARNING (storage.ensure_hierarchy); status says so, exit 1.
    root = _root_of(pki_dir)
    valid = _retired_with_days_left(pki_dir, "access", 10)
    (pki_dir / "access-retired.pem").write_bytes(pki.chain_pem(root, valid))

    rc = cli.main(["status"])

    retired = [line for line in capsys.readouterr().out.splitlines() if "(retired)" in line]
    assert rc == 1
    assert len(retired) == 2
    assert pki.read_identity(root)[0] in retired[0]
    assert "SKIPPED (its CN is not 'AdminHelper Access Intermediate'" in retired[0]
    assert pki.read_identity(valid)[0] in retired[1] and "SKIPPED" not in retired[1]


def test_status_without_a_root_lists_retired_ones_unchecked(monkeypatch, pki_dir, capsys):
    # Nothing to check them against: the missing root is the finding (3).
    other = _cert_with_days_left(monkeypatch, "access", 10)  # from a throwaway root
    (pki_dir / "access-retired.pem").write_bytes(pki.cert_to_pem(other))
    (pki_dir / "root.crt").unlink()

    assert cli.main(["status"]) == 3

    retired = [line for line in capsys.readouterr().out.splitlines() if "(retired)" in line]
    assert len(retired) == 1 and "SKIPPED" not in retired[0]


def test_rotate_with_the_secret_file(monkeypatch, pki_dir, tmp_path, capsys):
    secret = tmp_path / "passphrase"
    secret.write_bytes(PW + b"\n")
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", str(secret))
    _stdin(monkeypatch, "")  # not read: the file has it

    rc = cli.main(["rotate-intermediates"])

    out = capsys.readouterr().out
    assert rc == 0
    for scope in pki.SCOPES:
        assert f"{scope}:" in out
    # The gateway restarts only after the issuer is healthy, i.e. has re-minted its certs.
    steps = ("docker compose restart ca-issuer", "healthy", "docker compose restart gateway")
    at = [out.index(step) for step in steps]
    assert at == sorted(at)
    assert "restart ca-issuer gateway" not in out

    assert cli.main(["status"]) == 0
    retired = [line for line in capsys.readouterr().out.splitlines() if "(retired)" in line]
    assert len(retired) == len(pki.SCOPES)


def test_rotate_reads_the_passphrase_from_stdin(monkeypatch, pki_dir):
    before = storage.ensure_hierarchy(pki_dir, None)
    _stdin(monkeypatch, "pw\nnext line\n")

    assert cli.main(["rotate-intermediates"]) == 0

    after = storage.ensure_hierarchy(pki_dir, None)
    for scope in pki.SCOPES:
        assert after[scope].retired == (before[scope].cert,)


def test_rotate_asks_on_a_terminal(monkeypatch, pki_dir):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    prompts = []
    monkeypatch.setattr(sys, "stdin", Terminal("not read\n"))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompts.append(prompt) or "pw")

    assert cli.main(["rotate-intermediates"]) == 0
    assert len(prompts) == 1


def test_rotate_without_a_passphrase_changes_nothing(monkeypatch, pki_dir, capsys):
    before = _snapshot(pki_dir)
    _stdin(monkeypatch, "")

    assert cli.main(["rotate-intermediates"]) == 1

    assert "no passphrase" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


def test_rotate_with_an_unreadable_secret_file_changes_nothing(
    monkeypatch, pki_dir, tmp_path, capsys
):
    before = _snapshot(pki_dir)
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", str(tmp_path))  # a directory
    _stdin(monkeypatch, "pw\n")

    assert cli.main(["rotate-intermediates"]) == 1

    assert "passphrase" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


def test_rotate_with_a_wrong_passphrase_changes_nothing(pki_dir, tmp_path):
    # As its own process, so that the exit code and stderr are the ones an operator sees.
    before = _snapshot(pki_dir)
    env = {**os.environ, "CA_DATA_DIR": str(tmp_path)}
    env["CA_ROOT_PASSPHRASE_FILE"] = env["CA_ROOT_PASSPHRASE"] = ""

    done = subprocess.run(
        [sys.executable, "-m", "app.cli", "rotate-intermediates"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        input="not-the-passphrase\n",
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert done.returncode == 1, done.stderr
    assert "wrong passphrase" in done.stderr
    assert "Traceback" not in done.stdout + done.stderr
    assert _snapshot(pki_dir) == before
