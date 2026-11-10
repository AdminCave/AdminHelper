# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The operator CLI of the ca-issuer (R-0667): `status` shows root, current and retired
intermediates with their end, its exit code says whether one needs attention;
`rotate-intermediates` takes the root passphrase from the secret file, the terminal or
stdin and changes nothing when it has none or a wrong one. `rotate-root` (R-1021) runs the
steps of a root renewal, refuses a step its phase does not allow before it asks for a
passphrase, and `finish` waits for the certificate register; `status` shows the phase."""

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
from sqlalchemy import create_engine, insert, select
from sqlalchemy.pool import StaticPool

from app import cli, db, inventory, pki, root_rollover, rotation, storage
from tests import renewal

PW = b"pw"
NEXT_PW = renewal.NEXT_PW


@pytest.fixture
def pki_dir(monkeypatch, tmp_path):
    """A booted hierarchy under CA_DATA_DIR=tmp_path, no passphrase in the environment."""
    monkeypatch.setenv("CA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", "")
    monkeypatch.setenv("CA_ROOT_PASSPHRASE", "")
    monkeypatch.setenv("CA_NEXT_ROOT_PASSPHRASE_FILE", "")
    monkeypatch.setenv("CA_NEXT_ROOT_PASSPHRASE", "")
    monkeypatch.setenv("DATABASE_URL", "")
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


def test_status_marks_what_a_compromised_rotation_replaced(pki_dir, capsys):
    replaced = pki.cert_from_pem((pki_dir / "access.crt").read_bytes())
    saved = {
        n: (pki_dir / n).read_bytes() for n in ("access.crt", "access.key", "access-chain.pem")
    }
    rotation.rotate_intermediates(pki_dir, PW, compromised=frozenset({"access"}))
    (pki_dir / "access-retired.pem").write_bytes(pki.cert_to_pem(replaced))

    assert cli.main(["status"]) == 1
    out = capsys.readouterr().out.splitlines()
    retired = [line for line in out if line.startswith("access (retired)")]
    assert len(retired) == 1 and "SKIPPED (replaced with --compromised)" in retired[0]
    assert sum("SKIPPED" in line for line in out) == 1

    # Back as the current one, the boot refuses it: 3.
    for name, data in saved.items():
        (pki_dir / name).write_bytes(data)
    assert cli.main(["status"]) == 3
    out = capsys.readouterr().out.splitlines()
    current = [x for x in out if x.startswith("access ") and "(retired)" not in x]
    assert len(current) == 1
    assert "COMPROMISED (rotate-intermediates --compromised access)" in current[0]


def test_status_of_an_unreadable_register_is_3(pki_dir, capsys):
    rotation.compromised_path(pki_dir, "tunnel").write_bytes(b"-----BEGIN CERTIFICATE-----\nx\n")

    assert cli.main(["status"]) == 3
    assert "tunnel (compromised)" in capsys.readouterr().out


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


def test_rotate_compromised_keeps_nothing_of_that_scope(monkeypatch, pki_dir, capsys):
    before = storage.ensure_hierarchy(pki_dir, None)
    _stdin(monkeypatch, "pw\n")

    rc = cli.main(["rotate-intermediates", "--compromised", "tunnel"])

    out = capsys.readouterr().out
    assert rc == 0
    after = storage.ensure_hierarchy(pki_dir, None)
    assert after["tunnel"].retired == ()
    assert after["access"].retired == (before["access"].cert,)
    tunnel = out[out.index("tunnel:") : out.index("access:")]
    assert "compromised" in tunnel and "compromised" not in out[out.index("access:") :]


def test_rotate_refuses_an_unknown_compromised_scope(monkeypatch, pki_dir, capsys):
    before = _snapshot(pki_dir)
    _stdin(monkeypatch, "pw\n")

    with pytest.raises(SystemExit) as exc:
        cli.main(["rotate-intermediates", "--compromised", "acces"])

    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


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


# rotate-root and the status of a root renewal (R-1021).


class _Terminal(io.StringIO):
    def isatty(self):
        return True


def _terminal(monkeypatch, *entries: str) -> list[str]:
    """A terminal whose getpass returns `entries` in turn; returns the prompts asked."""
    prompts: list[str] = []
    answers = iter(entries)
    monkeypatch.setattr(sys, "stdin", _Terminal("not read\n"))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: prompts.append(prompt) or next(answers))
    return prompts


def _no_prompt(monkeypatch) -> None:
    def _asked(prompt):
        raise AssertionError(f"asked for {prompt!r}")

    monkeypatch.setattr(sys, "stdin", _Terminal(""))
    monkeypatch.setattr(getpass, "getpass", _asked)


def _secret_file(tmp_path: Path, name: str, value: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(value + b"\n")
    return path


def _phase(d: Path) -> str:
    return root_rollover.load_state(d).phase


def _decrypts(path: Path, passphrase: bytes) -> bool:
    try:
        pki.key_from_pem(path.read_bytes(), passphrase)
    except ValueError:
        return False
    return True


def _register(monkeypatch, installed_at=datetime.datetime(2020, 1, 1)):
    """An sqlite register behind DATABASE_URL as the server's migration leaves it, from
    `installed_at` (naive UTC) on; empty, and no ca-issuer start recorded yet."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(db.certificate_register_state), [{"id": 1, "installed_at": installed_at}]
        )
    monkeypatch.setenv("DATABASE_URL", "postgresql://ca:s3cret-pw@db.invalid/ah")
    monkeypatch.setattr(db, "make_engine", lambda url: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    return engine


def _start(engine, d: Path) -> None:
    """What a ca-issuer start writes: the snapshot of its certificates (main.record_inventory)."""
    inventory.record(engine, inventory.collect(d, None, None))


def _naive(at: datetime.datetime) -> datetime.datetime:
    return at.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _line(engine, subject: str, *, revoked: bool = False) -> str:
    """A device line of an agent; `revoked` as a replaced line."""
    line_id = os.urandom(16).hex()
    created = datetime.datetime(2025, 1, 1)
    with engine.begin() as conn:
        conn.execute(
            insert(db.device_lines),
            [
                {
                    "id": line_id,
                    "subject_id": subject,
                    "scope": "tunnel",
                    "kind": "agent",
                    "legacy": False,
                    "created_at": created,
                    "revoked_at": created if revoked else None,
                    "revoked_reason": "replaced" if revoked else None,
                }
            ],
        )
    return line_id


def _issue(
    engine,
    line_id: str,
    not_before: datetime.datetime,
    days: int = 30,
    recorded_at: datetime.datetime | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(db.issued_certificates),
            [
                {
                    "fingerprint": os.urandom(32).hex(),
                    "line_id": line_id,
                    "serial": os.urandom(8).hex(),
                    "not_before": _naive(not_before),
                    "not_after": _naive(not_before + datetime.timedelta(days=days)),
                    "renewed_from": None,
                    "created_at": _naive(recorded_at or not_before),
                }
            ],
        )


def _revoke_identity(engine, subject: str, at: datetime.datetime) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(db.revoked_identities),
            [{"id": subject, "subject_id": subject, "scope": "tunnel", "revoked_at": _naive(at)}],
        )


def _started_at(engine) -> datetime.datetime:
    """The ca-issuer's first start under the current root, as the inventory keeps it."""
    c = db.infra_certificates.c
    with engine.connect() as conn:
        at = conn.execute(select(c.recorded_at).where(c.name == "root")).scalar_one()
    return at.replace(tzinfo=datetime.timezone.utc)


def _switched(monkeypatch, d: Path, **register) -> tuple:
    """Phase switched with a register, the ca-issuer started under the new root; returns
    the engine and the time of that start."""
    renewal.renewed(monkeypatch, d, "switched")
    engine = _register(monkeypatch, **register)
    _start(engine, d)
    return engine, _started_at(engine)


def _stopped(monkeypatch, d: Path, name: str, target: str) -> None:
    """Let rotation.`name` raise when it reaches the file `target`, as a step that stops
    part way."""
    real = getattr(rotation, name)

    def _stop(path, *args):
        if path.name == target:
            raise rotation.RotationError("stopped")
        return real(path, *args)

    monkeypatch.setattr(rotation, name, _stop)


def test_rotate_root_stage_with_the_secret_file(monkeypatch, pki_dir, tmp_path, capsys):
    next_secret = _secret_file(tmp_path, "next", NEXT_PW)
    monkeypatch.setenv("CA_NEXT_ROOT_PASSPHRASE_FILE", str(next_secret))
    _no_prompt(monkeypatch)

    assert cli.main(["rotate-root", "stage"]) == 0

    state = root_rollover.load_state(pki_dir)
    assert state.phase == "staged"
    assert _decrypts(pki_dir / root_rollover.NEXT_KEY, NEXT_PW)
    out = capsys.readouterr().out
    assert pki.read_identity(state.next_root)[0] in out
    assert f"{root_rollover.ROTATE_ROOT} switch" in out
    assert "./scripts/backup.sh" in out
    # Only what enroll and renew hand out changed: gateway and frps keep theirs.
    assert cli._RESTART_ISSUER in out and "restart gateway" not in out


def test_rotate_root_stage_asks_twice_on_a_terminal(monkeypatch, pki_dir):
    prompts = _terminal(monkeypatch, "next-pw", "next-pw")

    assert cli.main(["rotate-root", "stage"]) == 0

    assert prompts == ["New root CA passphrase: ", "Repeat it: "]
    assert _decrypts(pki_dir / root_rollover.NEXT_KEY, NEXT_PW)


def test_rotate_root_stage_with_two_different_entries_changes_nothing(monkeypatch, pki_dir, capsys):
    before = _snapshot(pki_dir)
    _terminal(monkeypatch, "next-pw", "next-pv")

    assert cli.main(["rotate-root", "stage"]) == 1

    assert "the two passphrases entered differ" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


def test_rotate_root_stage_reads_the_first_line_of_stdin(monkeypatch, pki_dir):
    _stdin(monkeypatch, "next-pw\nnot read\n")

    assert cli.main(["rotate-root", "stage"]) == 0

    assert _decrypts(pki_dir / root_rollover.NEXT_KEY, NEXT_PW)


def test_rotate_root_stage_without_a_passphrase_changes_nothing(monkeypatch, pki_dir, capsys):
    # The root's passphrase is no stand-in for the new root's.
    monkeypatch.setenv("CA_ROOT_PASSPHRASE", "pw")
    before = _snapshot(pki_dir)
    _stdin(monkeypatch, "")

    assert cli.main(["rotate-root", "stage"]) == 1

    err = capsys.readouterr().err
    assert "no passphrase of the new root" in err and "CA_NEXT_ROOT_PASSPHRASE_FILE" in err
    assert _snapshot(pki_dir) == before


@pytest.mark.parametrize(
    ("phase", "step"),
    [
        ("none", "switch"),
        ("none", "finish"),
        ("staged", "stage"),
        ("staged", "finish"),
        ("switched", "stage"),
        ("switched", "switch"),
    ],
)
def test_rotate_root_refuses_a_step_of_another_phase_before_asking(
    monkeypatch, pki_dir, capsys, phase, step
):
    renewal.renewed(monkeypatch, pki_dir, phase)
    before = _snapshot(pki_dir)
    _no_prompt(monkeypatch)

    assert cli.main(["rotate-root", step]) == 1

    assert f"Error: {rotation.refusal(phase, step)}" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


def test_rotate_root_abort_removes_the_staged_root(pki_dir, capsys):
    before = _snapshot(pki_dir)
    rotation.stage_root(pki_dir, NEXT_PW)

    assert cli.main(["rotate-root", "abort"]) == 0

    assert _snapshot(pki_dir) == before
    assert cli._RESTART_ISSUER in capsys.readouterr().out


def test_rotate_root_abort_without_a_staged_root(pki_dir, capsys):
    assert cli.main(["rotate-root", "abort"]) == 1
    assert "cannot abort: no new root is staged" in capsys.readouterr().err


def test_rotate_root_switch_reads_the_root_then_the_new_root_from_stdin(
    monkeypatch, pki_dir, capsys
):
    rotation.stage_root(pki_dir, NEXT_PW)
    old_root = _root_of(pki_dir)
    _stdin(monkeypatch, "pw\nnext-pw\n")

    assert cli.main(["rotate-root", "switch"]) == 0

    state = root_rollover.load_state(pki_dir)
    assert state.phase == "switched" and state.cross is not None
    assert state.retired_root == old_root
    assert _decrypts(pki_dir / "root.key.enc", NEXT_PW)
    out = capsys.readouterr().out
    assert f"cross certificate: {pki.read_identity(state.cross)[0]}" in out
    assert out.count("  new: ") == len(pki.SCOPES)
    assert "compromised" not in out
    assert "rotate-intermediates needs its" in out
    assert "restart the ca-issuer right away" in out
    assert f"renewed since the restart: {root_rollover.ROTATE_ROOT} finish" in out
    assert "./scripts/backup.sh" in out and cli._RESTART in out


def test_rotate_root_switch_with_the_passphrases_swapped_changes_nothing(
    monkeypatch, pki_dir, capsys
):
    rotation.stage_root(pki_dir, NEXT_PW)
    before = _snapshot(pki_dir)
    _stdin(monkeypatch, "next-pw\npw\n")

    assert cli.main(["rotate-root", "switch"]) == 1

    assert "wrong passphrase" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


def test_rotate_root_switch_asks_on_a_terminal_once_each(monkeypatch, pki_dir):
    rotation.stage_root(pki_dir, NEXT_PW)
    prompts = _terminal(monkeypatch, "pw", "next-pw")

    assert cli.main(["rotate-root", "switch"]) == 0

    assert prompts == ["Root CA passphrase: ", "New root CA passphrase: "]


def test_rotate_root_switch_with_the_secret_files(monkeypatch, pki_dir, tmp_path):
    rotation.stage_root(pki_dir, NEXT_PW)
    monkeypatch.setenv("CA_ROOT_PASSPHRASE_FILE", str(_secret_file(tmp_path, "root", PW)))
    monkeypatch.setenv("CA_NEXT_ROOT_PASSPHRASE", "next-pw")
    _no_prompt(monkeypatch)

    assert cli.main(["rotate-root", "switch"]) == 0

    assert _phase(pki_dir) == "switched"


def test_rotate_root_switch_without_cross_asks_only_for_the_new_root(monkeypatch, pki_dir, capsys):
    rotation.stage_root(pki_dir, NEXT_PW)
    _stdin(monkeypatch, "next-pw\n")

    assert cli.main(["rotate-root", "switch", "--no-cross"]) == 0

    state = root_rollover.load_state(pki_dir)
    assert state.phase == "switched" and state.cross is None and not state.switch.cross
    assert "no cross certificate: a client that trusts only" in capsys.readouterr().out


def test_rotate_root_switch_compromised(monkeypatch, pki_dir, capsys):
    rotation.stage_root(pki_dir, NEXT_PW)
    _stdin(monkeypatch, "pw\nnext-pw\n")

    assert cli.main(["rotate-root", "switch", "--compromised", "access"]) == 0

    switch = root_rollover.load_state(pki_dir).switch
    assert switch.compromised == ("access",) and switch.drop_retired_root
    out = capsys.readouterr().out
    assert out.count("  compromised: ") == 1
    assert "revoke the devices of this scope" in out


def test_rotate_root_switch_refuses_compromised_without_cross(pki_dir, capsys):
    rotation.stage_root(pki_dir, NEXT_PW)
    before = _snapshot(pki_dir)

    with pytest.raises(SystemExit) as exc:
        cli.main(["rotate-root", "switch", "--no-cross", "--compromised", "access"])

    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
    assert _snapshot(pki_dir) == before


def test_rotate_root_switch_ends_a_switch_that_stopped_without_the_old_root(
    monkeypatch, pki_dir, capsys
):
    rotation.stage_root(pki_dir, NEXT_PW)
    with monkeypatch.context() as m:
        _stopped(m, pki_dir, "_replace", "root.key.enc")
        with pytest.raises(rotation.RotationError):
            rotation.switch_root(pki_dir, NEXT_PW, PW)
    assert _phase(pki_dir) == "switching"

    assert cli.main(["status"]) == 3
    out = capsys.readouterr().out
    assert "root renewal: a switch stopped part way" in out
    assert f"{root_rollover.ROTATE_ROOT} switch, with the same options" in out

    _stdin(monkeypatch, "next-pw\n")  # no line for the old root: the cross certificate is there
    assert cli.main(["rotate-root", "switch"]) == 0
    assert _phase(pki_dir) == "switched"


def test_rotate_root_finish_once_every_device_renewed_since_the_restart(
    monkeypatch, pki_dir, capsys
):
    engine, started_at = _switched(monkeypatch, pki_dir)
    old, new = started_at - datetime.timedelta(days=1), started_at + datetime.timedelta(seconds=1)
    renewed = _line(engine, "renewed")
    _issue(engine, renewed, old)
    _issue(engine, renewed, new)
    _issue(engine, _line(engine, "fresh"), new)
    # Not counted: a replaced line, a revoked identity, a certificate that has run out.
    _issue(engine, _line(engine, "replaced", revoked=True), old)
    _issue(engine, _line(engine, "gone"), old)
    _revoke_identity(engine, "gone", old + datetime.timedelta(hours=1))
    _issue(engine, _line(engine, "expired"), old - datetime.timedelta(days=40))

    assert cli.main(["status"]) == 0
    assert (
        "  devices: 2 active, 2 renewed since the stage, 2 since the restart under the new root"
        in capsys.readouterr().out
    )

    assert cli.main(["rotate-root", "finish"]) == 0

    assert _phase(pki_dir) == "none"
    out = capsys.readouterr().out
    assert "the root renewal is finished" in out
    assert "./scripts/backup.sh" in out and cli._RESTART in out


def test_rotate_root_finish_waits_for_devices_from_before_the_restart(monkeypatch, pki_dir, capsys):
    engine, started_at = _switched(monkeypatch, pki_dir)
    old = started_at - datetime.timedelta(days=1)
    _issue(engine, _line(engine, "behind"), old, days=30)
    _issue(engine, _line(engine, "ahead"), started_at + datetime.timedelta(seconds=1))
    before = _snapshot(pki_dir)

    assert cli.main(["rotate-root", "finish"]) == 1

    err = capsys.readouterr().err
    assert (
        "1 active device(s) still hold a certificate from before the restart under the new root"
        in err
    )
    assert f"the last ends on {(old + datetime.timedelta(days=30)).isoformat()}" in err
    assert "browser certificates need a new enrollment" in err and "--force" in err
    assert _snapshot(pki_dir) == before

    assert cli.main(["rotate-root", "finish", "--force"]) == 0
    assert _phase(pki_dir) == "none"


@pytest.mark.parametrize("started", ["never", "under the old root"])
def test_rotate_root_finish_waits_for_a_start_under_the_new_root(
    monkeypatch, pki_dir, capsys, started
):
    # Until it restarts, the ca-issuer signs under the old root.
    engine = _register(monkeypatch)
    if started != "never":
        _start(engine, pki_dir)
    renewal.renewed(monkeypatch, pki_dir, "switched")

    assert cli.main(["status"]) == 0
    assert "none under the new root yet: the ca-issuer has not restarted" in capsys.readouterr().out
    assert cli.main(["rotate-root", "finish"]) == 1
    assert "has not started under the new root since the switch" in capsys.readouterr().err

    _start(engine, pki_dir)
    assert cli.main(["rotate-root", "finish"]) == 0


def test_rotate_root_finish_counts_a_device_from_the_first_restart_under_the_new_root_on(
    monkeypatch, pki_dir, capsys
):
    # Between the switch and the restart the old process still signs under the old root; a
    # later restart does not move that limit.
    renewal.renewed(monkeypatch, pki_dir, "switched")
    engine = _register(monkeypatch)
    switched_at = root_rollover.load_state(pki_dir).switch.switched_at
    restart = switched_at + datetime.timedelta(hours=1)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: restart)
        _start(engine, pki_dir)
    line = _line(engine, "in-between")
    _issue(engine, line, switched_at + datetime.timedelta(minutes=1))

    assert cli.main(["status"]) == 0
    assert (
        "  devices: 1 active, 1 renewed since the stage, 0 since the restart under the new root"
        in (capsys.readouterr().out)
    )
    assert cli.main(["rotate-root", "finish"]) == 1
    assert "1 active device(s) still hold a certificate from before the restart" in (
        capsys.readouterr().err
    )

    _issue(engine, line, restart + datetime.timedelta(seconds=1))
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: restart + datetime.timedelta(days=1))
        _start(engine, pki_dir)
    assert _started_at(engine) == restart
    assert cli.main(["rotate-root", "finish"]) == 0


@pytest.mark.parametrize("recorded", ["after the start", "before the start"])
def test_rotate_root_finish_decides_a_renewal_in_the_second_of_the_start_by_its_record(
    monkeypatch, pki_dir, capsys, recorded
):
    # A leaf's not_before holds whole seconds; the start under the new root has microseconds.
    # Within that second the time the issuing process recorded the leaf decides.
    renewal.renewed(monkeypatch, pki_dir, "switched")
    engine = _register(monkeypatch)
    restart = root_rollover.load_state(pki_dir).switch.switched_at.replace(
        microsecond=500_000
    ) + datetime.timedelta(hours=1)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: restart)
        _start(engine, pki_dir)
    assert _started_at(engine) == restart
    step = datetime.timedelta(milliseconds=1)
    at = restart + step if recorded == "after the start" else restart - step
    _issue(engine, _line(engine, "same-second"), restart.replace(microsecond=0), recorded_at=at)

    since = 1 if recorded == "after the start" else 0
    assert cli.main(["status"]) == 0
    assert f"{since} since the restart under the new root" in capsys.readouterr().out
    assert cli.main(["rotate-root", "finish"]) == (0 if since else 1)
    held = "still hold a certificate from before the restart" in capsys.readouterr().err
    assert held == (since == 0)


def test_rotate_root_finish_waits_while_the_register_may_miss_a_device(
    monkeypatch, pki_dir, capsys
):
    # The register came after the old root: a certificate from before it may still renew
    # (tokens.legacy_admitted) and the register then learns of its device.
    installed_at = _root_of(pki_dir).not_valid_before_utc + datetime.timedelta(hours=1)
    _switched(monkeypatch, pki_dir, installed_at=_naive(installed_at))
    end = installed_at + cli.tokens.LEGACY_WINDOW

    assert cli.main(["rotate-root", "finish"]) == 1
    assert f"the register does not know every device until {end.isoformat()}" in (
        capsys.readouterr().err
    )

    after = end + datetime.timedelta(seconds=1)
    monkeypatch.setattr(pki, "_now", lambda: after)
    assert cli.main(["rotate-root", "finish"]) == 0


def test_rotate_root_finish_without_a_register_changes_nothing(monkeypatch, pki_dir, capsys):
    renewal.renewed(monkeypatch, pki_dir, "switched")
    before = _snapshot(pki_dir)

    assert cli.main(["rotate-root", "finish"]) == 1

    err = capsys.readouterr().err
    assert "the certificate register is unknown (no DATABASE_URL)" in err
    assert "finish --force goes ahead anyway" in err
    assert _snapshot(pki_dir) == before


def _connect_quoting_the_url(url):
    raise RuntimeError(f"could not connect to {url}")


@pytest.mark.parametrize(
    ("engine", "error"),
    [
        (lambda url: create_engine("sqlite://", poolclass=StaticPool), "OperationalError"),
        (_connect_quoting_the_url, "RuntimeError"),
    ],
    ids=["no tables", "no connection"],
)
def test_an_unreadable_register_is_named_without_the_url(
    monkeypatch, pki_dir, capsys, engine, error
):
    renewal.renewed(monkeypatch, pki_dir, "switched")
    monkeypatch.setenv("DATABASE_URL", "postgresql://ca:s3cret-pw@db.invalid/ah")
    monkeypatch.setattr(db, "make_engine", engine)

    assert cli.main(["rotate-root", "finish"]) == 1
    assert cli.main(["status"]) == 0

    captured = capsys.readouterr()
    assert f"the certificate register is unknown (database error {error})" in captured.err
    assert f"  devices: unknown (database error {error})" in captured.out
    assert "s3cret-pw" not in captured.out + captured.err
    assert "db.invalid" not in captured.out + captured.err


def test_rotate_root_finish_ends_a_finish_that_stopped_without_the_register(
    monkeypatch, pki_dir, capsys
):
    # It has taken the old root out of bundles already; waiting for devices is over.
    renewal.renewed(monkeypatch, pki_dir, "switched")
    with monkeypatch.context() as m:
        _stopped(m, pki_dir, "_remove", root_rollover.RETIRED)
        with pytest.raises(rotation.RotationError):
            rotation.finish_root(pki_dir)
    assert _phase(pki_dir) == "finishing"

    assert cli.main(["status"]) == 3
    out = capsys.readouterr().out
    assert "root renewal: a finish stopped part way" in out

    assert cli.main(["rotate-root", "finish"]) == 0
    assert _phase(pki_dir) == "none"


@pytest.mark.parametrize(("role", "code"), [("root", 1), ("access", 0)])
def test_status_warns_of_the_root_a_year_ahead(monkeypatch, pki_dir, capsys, role, code):
    # A new root reaches the clients only with their renewals (pki.ROOT_WARN_DAYS).
    cert = _cert_with_days_left(monkeypatch, role, 200)
    name = "root.crt" if role == "root" else f"{role}.crt"
    (pki_dir / name).write_bytes(pki.cert_to_pem(cert))

    assert cli.main(["status"]) == code
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith(f"{role} "))
    assert line.endswith("WARNING") == (code == 1)


def test_status_without_a_renewal_does_not_read_the_register(monkeypatch, pki_dir, capsys):
    def _no_engine(url):
        raise AssertionError("no register read in phase none")

    monkeypatch.setenv("DATABASE_URL", "postgresql://ca:pw@db.invalid/ah")
    monkeypatch.setattr(db, "make_engine", _no_engine)

    assert cli.main(["status"]) == 0
    assert "root renewal" not in capsys.readouterr().out


def test_status_of_a_staged_renewal(monkeypatch, pki_dir, capsys):
    new_root = rotation.stage_root(pki_dir, NEXT_PW)

    assert cli.main(["status"]) == 0

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[1].startswith("root (next)") and pki.read_identity(new_root)[0] in lines[1]
    staged_at = new_root.not_valid_before_utc.isoformat()
    assert f"root renewal: staged on {staged_at}, the current root still signs" in out
    assert "  devices: unknown (no DATABASE_URL)" in out
    assert (
        f"  next: once every device has renewed since the stage: {root_rollover.ROTATE_ROOT} switch"
        in out
    )


def test_status_of_a_staged_renewal_counts_the_devices(monkeypatch, pki_dir, capsys):
    new_root = rotation.stage_root(pki_dir, NEXT_PW)
    staged_at = new_root.not_valid_before_utc
    engine = _register(monkeypatch)
    _issue(engine, _line(engine, "behind"), staged_at - datetime.timedelta(days=1))
    _issue(engine, _line(engine, "ahead"), staged_at + datetime.timedelta(seconds=1))

    assert cli.main(["status"]) == 0

    assert "  devices: 2 active, 1 renewed since the stage\n" in capsys.readouterr().out


def test_status_after_the_switch(monkeypatch, pki_dir, capsys):
    engine, started_at = _switched(monkeypatch, pki_dir)
    state = root_rollover.load_state(pki_dir)
    switched_at = state.switch.switched_at
    staged_at = _root_of(pki_dir).not_valid_before_utc
    _issue(engine, _line(engine, "behind"), staged_at - datetime.timedelta(days=1))
    _issue(engine, _line(engine, "ahead"), started_at + datetime.timedelta(seconds=1))

    assert cli.main(["status"]) == 0

    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[1].startswith("root (retired)") and "WARNING" not in lines[1]
    assert pki.read_identity(state.retired_root)[0] in lines[1]
    assert lines[2].startswith("root (cross)")
    # The intermediates the switch replaced are under the old root, which the boot still trusts.
    retired = [x for x in lines if " (retired)" in x and not x.startswith("root")]
    assert len(retired) == len(pki.SCOPES) and not any("SKIPPED" in x for x in retired)
    assert f"root renewal: switched on {switched_at.isoformat()} (cross certificate)" in out
    assert (
        "  devices: 2 active, 1 renewed since the stage, 1 since the restart under the new root"
        in out
    )
    assert f"since the restart under the new root: {root_rollover.ROTATE_ROOT} finish" in out


def test_status_after_a_compromised_switch_trusts_the_old_root_for_no_scope_of_it(
    monkeypatch, pki_dir, capsys
):
    # The boot takes retired ones of a compromised scope from the new root only.
    r = renewal.renewed(monkeypatch, pki_dir, "compromised", compromised="access")
    (pki_dir / "access-retired.pem").write_bytes(pki.cert_to_pem(r.before["access"].cert))

    assert cli.main(["status"]) == 1

    out = capsys.readouterr().out
    access = [x for x in out.splitlines() if x.startswith("access (retired)")]
    assert len(access) == 1 and "SKIPPED" in access[0]
    tunnel = [x for x in out.splitlines() if x.startswith("tunnel (retired)")]
    assert tunnel and not any("SKIPPED" in x for x in tunnel)
    assert "compromised: access; the old root is out of `chain`" in out


def test_status_after_the_switch_without_cross(monkeypatch, pki_dir, capsys):
    renewal.renewed(monkeypatch, pki_dir, "no-cross")

    assert cli.main(["status"]) == 0

    out = capsys.readouterr().out
    assert "root (cross)" not in out
    assert "(no cross certificate)" in out


def test_status_of_an_old_root_that_ran_out_before_finish(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CA_DATA_DIR", str(tmp_path / "late"))
    for name in ("CA_ROOT_PASSPHRASE_FILE", "CA_ROOT_PASSPHRASE", "DATABASE_URL"):
        monkeypatch.setenv(name, "")
    renewal.renewed(monkeypatch, tmp_path / "late" / "pki", "expired")

    assert cli.main(["status"]) == 1

    retired_root = next(
        x for x in capsys.readouterr().out.splitlines() if x.startswith("root (retired)")
    )
    assert retired_root.endswith("WARNING (finish pending)")


def test_status_and_rotate_root_of_an_unreadable_renewal(monkeypatch, pki_dir, capsys):
    # No switch or finish leaves a cross certificate without the record of the switch.
    (pki_dir / root_rollover.CROSS).write_bytes(pki.cert_to_pem(_root_of(pki_dir)))
    _no_prompt(monkeypatch)

    assert cli.main(["status"]) == 3
    assert "root renewal: unreadable, " in capsys.readouterr().out

    assert cli.main(["rotate-root", "stage"]) == 1
    assert f"without {root_rollover.STATE}" in capsys.readouterr().err
