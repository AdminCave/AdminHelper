# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operator CLI of the ca-issuer — run in a one-off container of the service:

    docker compose run --rm --no-deps ca-issuer python -m app.cli status
    docker compose run --rm --no-deps ca-issuer python -m app.cli rotate-intermediates
    docker compose run --rm --no-deps ca-issuer python -m app.cli rotate-root stage

``run``, not ``exec``: it also works while the issuer is stopped or no longer starts
(an expired intermediate), and the entrypoint drops it to the ``app`` user like the
service. ``status`` reads certificates, during a root renewal also the certificate
register in the database. ``rotate-intermediates`` needs the root passphrase: from the
secret file or env var the service reads, else asked on the terminal, else the first
line of stdin — never as an argument, which ``ps`` shows. ``rotate-root`` (R-1021) reads
the passphrase of the new root the same way from CA_NEXT_ROOT_PASSPHRASE_FILE or
CA_NEXT_ROOT_PASSPHRASE; ``switch`` asks for the root's before the new root's.

Listings go to stdout, errors to stderr."""

from __future__ import annotations

import argparse
import datetime
import getpass
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from sqlalchemy import Connection, select

from app import config, db, pki, root_rollover, rotation, tokens
from app.root_rollover import ROTATE_ROOT

# status: 0 all fine, 1 the root has fewer than pki.ROOT_WARN_DAYS left, a current
# intermediate fewer than pki.EXPIRY_WARN_DAYS, or the old root of a root renewal has
# expired before its finish; 3 one of them is not valid now or not readable, or a step of
# a root renewal stopped part way (2 is argparse's usage error). Retired intermediates
# never raise it by their time: they run out by design. An entry of a retired file that
# the boot skips with a WARNING (not an intermediate of its scope under a root it trusts,
# pki.intermediate_problem_among) is 1, marked SKIPPED.
OK, WARN, BAD = 0, 1, 3

_ROLE_WIDTH = len(f"{max(pki.SCOPES, key=len)} (retired)")
_CN_WIDTH = len("AdminHelper Internal Intermediate YYYY-MM-DD")  # pads, never cuts
# Not `restart ca-issuer gateway`: the gateway reads its certificates only at its own start
# and would read them before the issuer has re-minted them under the new intermediates.
# Not depends_on service_healthy in compose either: a ca-issuer that does not start would
# then take :443 down with it.
_RESTART = (
    "restart:\n"
    "  docker compose restart ca-issuer\n"
    "  wait until docker compose ps shows ca-issuer as healthy\n"
    "  docker compose restart gateway  (frps follows by itself)"
)
# stage and abort change only what enroll and renew hand out; gateway and frps keep theirs.
_RESTART_ISSUER = "restart:\n  docker compose restart ca-issuer"
_BACKUP = "back up the PKI volume now, the way back from the next step: ./scripts/backup.sh"


def status(pki_dir: Path) -> int:
    """Print root.crt and the roots of a root renewal, then per scope <scope>.crt and the
    entries of <scope>-retired.pem, one line each, then where a root renewal stands;
    return the exit code (see OK, WARN, BAD)."""
    now = pki._now()
    try:
        renewal: root_rollover.State | None = root_rollover.load_state(pki_dir)
        renewal_error = ""
    except root_rollover.RolloverError as exc:
        renewal, renewal_error = None, str(exc)
    worst = _show_current("root", pki_dir / "root.crt", now, pki.ROOT_WARN_DAYS)
    try:
        root: x509.Certificate | None = pki.cert_from_pem((pki_dir / "root.crt").read_bytes())
    except (OSError, ValueError):
        root = None  # shown as unreadable above; the retired entries go unchecked
    if renewal is not None:
        worst = max(worst, _show_renewal_roots(pki_dir, renewal, now))
    for scope in pki.SCOPES:
        worst = max(worst, _show_current(scope, pki_dir / f"{scope}.crt", now))
        signers = () if root is None else _signers(renewal, root, scope)
        worst = max(worst, _show_retired(scope, pki_dir / f"{scope}-retired.pem", now, signers))
    if renewal is None:
        print(f"root renewal: unreadable, {renewal_error}")
        return BAD
    return max(worst, _show_renewal(renewal, root, now))


def _show_current(
    role: str, path: Path, now: datetime.datetime, warn_days: int = pki.EXPIRY_WARN_DAYS
) -> int:
    try:
        cert = pki.cert_from_pem(path.read_bytes())
    except (OSError, ValueError) as exc:
        return _unreadable(role, path, exc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        print(_line(role, cert, now))
        return BAD
    if pki.days_left(cert, now) < warn_days:  # the boot WARNING's rule
        print(f"{_line(role, cert, now)}  WARNING")
        return WARN
    print(_line(role, cert, now))
    return OK


def _show_renewal_roots(pki_dir: Path, renewal: root_rollover.State, now: datetime.datetime) -> int:
    """The new root while staged, the old root and the cross certificate after the switch.
    Neither of the latter two is rated by its time, both leave with finish; an old root
    that has expired before it is 1 (the boot WARNING)."""
    if renewal.phase == "staged":
        return _show_current(
            "root (next)", pki_dir / root_rollover.NEXT_CRT, now, pki.ROOT_WARN_DAYS
        )
    worst = OK
    if renewal.retired_root is not None:
        old_root = renewal.retired_root
        if now >= old_root.not_valid_after_utc:
            print(f"{_line('root (retired)', old_root, now)}  WARNING (finish pending)")
            worst = WARN
        else:
            print(_line("root (retired)", old_root, now))
    if renewal.cross is not None:
        print(_line("root (cross)", renewal.cross, now))
    return worst


def _signers(
    renewal: root_rollover.State | None, root: x509.Certificate, scope: str
) -> tuple[x509.Certificate, ...]:
    """The roots the boot accepts the retired intermediates of `scope` from
    (storage.ensure_hierarchy): the old root too after the switch, unless the switch or a
    later rotate-intermediates --compromised marked the scope compromised."""
    if (
        renewal is not None
        and renewal.phase == "switched"
        and scope not in renewal.switch.compromised
    ):
        return (root, renewal.retired_root)
    return (root,)


def _show_renewal(
    renewal: root_rollover.State, root: x509.Certificate | None, now: datetime.datetime
) -> int:
    """Where a root renewal stands and the next step; nothing in phase none."""
    if renewal.phase == "none":
        return OK
    if renewal.phase in ("switching", "finishing"):
        step = "switch" if renewal.phase == "switching" else "finish"
        same = ", with the same options" if step == "switch" else ""
        print(
            f"root renewal: a {step} stopped part way, the ca-issuer does not start until it "
            f"ends; end it with: {ROTATE_ROOT} {step}{same}"
        )
        return BAD
    if renewal.phase == "staged":
        staged_at = renewal.next_root.not_valid_before_utc
        print(f"root renewal: staged on {staged_at.isoformat()}, the current root still signs")
        print(f"  {_coverage(now, staged_at, None)}")
        print(f"  next: once every device has renewed since the stage: {ROTATE_ROOT} switch")
        return OK
    switch = renewal.switch
    options = ["cross certificate" if switch.cross else "no cross certificate"]
    if switch.compromised:
        options.append(f"compromised: {', '.join(switch.compromised)}")
    if switch.drop_retired_root:
        options.append("the old root is out of `chain`")
    print(f"root renewal: switched on {switch.switched_at.isoformat()} ({'; '.join(options)})")
    staged_at = None if root is None else root.not_valid_before_utc
    print(f"  {_coverage(now, staged_at, root)}")
    print(
        "  next: once every device has renewed since the restart under the new root: "
        f"{ROTATE_ROOT} finish"
    )
    return OK


def _coverage(
    now: datetime.datetime,
    staged_at: datetime.datetime | None,
    new_root: x509.Certificate | None,
) -> str:
    """How many devices of the register have their newest certificate from after the stage
    and, once switched to `new_root`, from after the ca-issuer's first start under it."""
    try:
        register = _read_register(now)
    except _RegisterUnknown as exc:
        return f"devices: unknown ({exc})"
    parts = [f"devices: {len(register.devices)} active"]
    if staged_at is not None:
        since = sum(1 for d in register.devices if d.not_before >= staged_at)
        parts.append(f"{since} renewed since the stage")
    if new_root is not None:
        if register.started_root == new_root.fingerprint(hashes.SHA256()).hex():
            since = sum(1 for d in register.devices if d.signed_since(register.started_at))
            parts.append(f"{since} since the restart under the new root")
        else:
            parts.append("none under the new root yet: the ca-issuer has not restarted")
    return ", ".join(parts)


def _show_retired(
    scope: str, path: Path, now: datetime.datetime, signers: tuple[x509.Certificate, ...]
) -> int:
    role = f"{scope} (retired)"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return OK  # no rotation yet
    except OSError as exc:
        return _unreadable(role, path, exc)
    try:
        certs = x509.load_pem_x509_certificates(data) if data.strip() else []
    except ValueError as exc:
        # The issuer does not start with a retired file it cannot read.
        return _unreadable(role, path, exc)
    worst = OK
    for cert in certs:
        # The boot's rule (storage.ensure_hierarchy): such an entry is skipped whatever its time.
        if signers and (problem := pki.intermediate_problem_among(cert, scope, signers)):
            print(f"{_line(role, cert, now)}  SKIPPED ({problem})")
            worst = WARN
        else:
            print(_line(role, cert, now))
    return worst


def _unreadable(role: str, path: Path, exc: Exception) -> int:
    reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
    print(f"{role:<{_ROLE_WIDTH}}  unreadable: {path} ({reason})")
    return BAD


def _line(role: str, cert: x509.Certificate, now: datetime.datetime) -> str:
    if now >= cert.not_valid_after_utc:
        left = "EXPIRED"
    elif now < cert.not_valid_before_utc:
        left = "NOT YET VALID"
    else:
        left = f"{pki.days_left(cert, now)} days left"
    return (
        f"{role:<{_ROLE_WIDTH}}  {pki.read_identity(cert)[0]:<{_CN_WIDTH}}  "
        f"notAfter {cert.not_valid_after_utc.isoformat()}  {left}"
    )


def rotate(pki_dir: Path, compromised: frozenset[str] = frozenset()) -> int:
    """Rotate the intermediates of every scope (rotation.rotate_intermediates), keeping
    nothing replaced of the `compromised` ones; 0 done, 1 no passphrase or the rotation
    failed, with the reason on stderr."""
    try:
        passphrase = config.root_passphrase()
    except OSError as exc:
        print(f"Error: cannot read the root passphrase: {exc}", file=sys.stderr)
        return 1
    if not passphrase:
        passphrase = _ask_passphrase()
    if not passphrase:
        print(
            "Error: no passphrase — none in CA_ROOT_PASSPHRASE_FILE or CA_ROOT_PASSPHRASE, "
            "none entered on the terminal or as the first line of stdin",
            file=sys.stderr,
        )
        return 1
    try:
        rotated = rotation.rotate_intermediates(pki_dir, passphrase, compromised)
    except rotation.RotationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for r in rotated:
        print(f"{r.scope}:")
        print(f"  old: {_name_and_end(r.old)}")
        print(f"  new: {_name_and_end(r.new)}")
        if r.scope in compromised:
            print("  compromised: no replaced intermediate is renewed or in a trust bundle; a")
            print("  client sending it along still passes TLS, so revoke the devices of this")
            print("  scope and set them up anew; only a new root closes the leak")
    print(_RESTART)
    return 0


class _Refused(Exception):
    """A step of rotate-root does not run; the message says why."""


def rotate_root(
    pki_dir: Path,
    step: str,
    compromised: frozenset[str] = frozenset(),
    cross: bool = True,
    force: bool = False,
) -> int:
    """One step of a root renewal (rotation.stage_root, abort_root, switch_root,
    finish_root); 0 done, 1 refused or failed, with the reason on stderr. A step the
    phase does not allow is refused before any passphrase is asked for."""
    try:
        if step == "stage":
            _stage(pki_dir)
        elif step == "abort":
            _abort(pki_dir)
        elif step == "switch":
            _switch(pki_dir, compromised, cross)
        else:
            _finish(pki_dir, force)
    except (_Refused, rotation.RotationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _stage(pki_dir: Path) -> None:
    renewal = _renewal(pki_dir)
    if renewal.phase != "none":
        raise _Refused(rotation.refusal(renewal.phase, "stage"))
    # A typo here would only show at the switch, which then cannot decrypt the new key.
    passphrase = _passphrase(_NEXT_ROOT, confirm=True)
    new_root = rotation.stage_root(pki_dir, passphrase)
    print(f"new root: {_name_and_end(new_root)}")
    print("the current root still signs; enroll and renew hand out the new root beside it")
    print(f"next: once every device has renewed since now: {ROTATE_ROOT} switch")
    print(_BACKUP)
    print(_RESTART_ISSUER)


def _abort(pki_dir: Path) -> None:
    rotation.abort_root(pki_dir)
    print("the staged new root is removed; enroll and renew hand out the current root alone")
    print(_RESTART_ISSUER)


def _switch(pki_dir: Path, compromised: frozenset[str], cross: bool) -> None:
    renewal = _renewal(pki_dir)
    if renewal.phase not in ("staged", "switching"):
        raise _Refused(rotation.refusal(renewal.phase, "switch"))
    # The old root's key signs the cross certificate, and only while it is not written.
    root_passphrase = _passphrase(_ROOT) if cross and renewal.cross is None else None
    next_passphrase = _passphrase(_NEXT_ROOT)
    switched = rotation.switch_root(pki_dir, next_passphrase, root_passphrase, compromised, cross)
    print(f"new root: {_name_and_end(switched.root)}")
    print(f"old root: {_name_and_end(switched.retired_root)}, trusted until finish")
    if switched.cross is not None:
        print(f"cross certificate: {_name_and_end(switched.cross)}")
    else:
        print("no cross certificate: a client that trusts only the old root loses the server")
    for r in switched.rotated:
        print(f"{r.scope}:")
        print(f"  old: {_name_and_end(r.old)}")
        print(f"  new: {_name_and_end(r.new)}")
        if r.scope in compromised:
            print("  compromised: no replaced intermediate is renewed or in a trust bundle, and")
            print("  the old root is out of `chain`; revoke the devices of this scope and set")
            print("  them up anew")
    print("root.key.enc now holds the key of the new root: rotate-intermediates needs its")
    print("passphrase from now on (also in CA_ROOT_PASSPHRASE_FILE, if you keep it there)")
    print("restart the ca-issuer right away: until then it signs under the old root, and")
    print("finish counts a device only once it has renewed after that restart")
    print(f"next: once every device has renewed since the restart: {ROTATE_ROOT} finish")
    print(_BACKUP)
    print(_RESTART)


def _finish(pki_dir: Path, force: bool) -> None:
    renewal = _renewal(pki_dir)
    if renewal.phase not in ("switched", "finishing"):
        raise _Refused(rotation.refusal(renewal.phase, "finish"))
    # A finish that stopped part way has already taken the old root out of some bundles.
    if renewal.phase == "switched" and not force:
        if reason := _finish_lock(pki_dir, renewal, pki._now()):
            raise _Refused(
                f"cannot finish: {reason}; finish --force goes ahead anyway, and the devices "
                "still under the old root lose the server"
            )
    rotation.finish_root(pki_dir)
    print("the root renewal is finished: the old root, the cross certificate and the")
    print("intermediates under the old root are in no bundle any more")
    print(_BACKUP)
    print(_RESTART)


def _renewal(pki_dir: Path) -> root_rollover.State:
    try:
        return root_rollover.load_state(pki_dir)
    except root_rollover.RolloverError as exc:
        raise _Refused(str(exc)) from exc


def _finish_lock(pki_dir: Path, renewal: root_rollover.State, now: datetime.datetime) -> str | None:
    """Why the register says a device may still depend on the old root, or None."""
    try:
        root = pki.cert_from_pem((pki_dir / "root.crt").read_bytes())
    except (OSError, ValueError) as exc:
        return f"cannot read {pki_dir / 'root.crt'} ({exc})"
    try:
        register = _read_register(now)
    except _RegisterUnknown as exc:
        return f"the certificate register is unknown ({exc}), so is who still needs the old root"
    if register.started_root != root.fingerprint(hashes.SHA256()).hex():
        return (
            "the ca-issuer has not started under the new root since the switch and may "
            "still sign under the old one; restart it, then finish"
        )
    installed_at, old_root = register.installed_at, renewal.retired_root
    if (
        installed_at is not None
        and old_root.not_valid_before_utc < installed_at
        and now < installed_at + tokens.LEGACY_WINDOW
    ):
        # tokens.legacy_admitted: until then a certificate from before the register may still
        # renew onto it, so a device the register has not seen yet can depend on the old root.
        return (
            f"the register does not know every device until "
            f"{(installed_at + tokens.LEGACY_WINDOW).isoformat()}"
        )
    # From the first start under the new root on the ca-issuer signs under it; what the old
    # process signed between the switch and that restart still needs the old root.
    if pending := [d for d in register.devices if not d.signed_since(register.started_at)]:
        last = max(d.not_after for d in pending)
        return (
            f"{len(pending)} active device(s) still hold a certificate from before the restart "
            f"under the new root (the last ends on {last.isoformat()}): agents and desktops "
            "renew by themselves, browser certificates need a new enrollment, revoke the "
            "devices that are gone"
        )
    return None


class _RegisterUnknown(Exception):
    """The register cannot be read; the message says why, without the DB URL."""


@dataclass(frozen=True)
class _Device:
    # Of the newest certificate of an active device line, aware UTC.
    not_before: datetime.datetime
    not_after: datetime.datetime
    recorded_at: datetime.datetime  # issued_certificates.created_at

    def signed_since(self, at: datetime.datetime) -> bool:
        """Whether the certificate was signed at `at` or later. not_before holds whole
        seconds (the signing time cut down), so within the second of `at` it cannot tell;
        there the time the issuing process recorded it decides. That process records the
        start before it serves a request and takes both times from the same clock, so a
        certificate of the process before the restart is recorded before the start and one
        of the new process at or after it. A certificate taken over from before the register
        is recorded by the server's database clock when it is taken over, long after it was
        signed: an old one counts as new only if the register was installed in the second of
        the start, which can only end the hold early, never extend trust."""
        second = at.replace(microsecond=0)
        if self.not_before != second:
            return self.not_before > second
        return self.recorded_at >= at


@dataclass(frozen=True)
class _Register:
    # Lines not revoked, whose identity is not revoked and whose newest certificate is
    # valid now: the devices that still reach the server.
    devices: list[_Device]
    installed_at: datetime.datetime | None  # certificate_register_state, aware UTC
    started_root: str | None  # SHA-256 of the root the ca-issuer last started with
    started_at: datetime.datetime | None  # its first start under that root, aware UTC


def _read_register(now: datetime.datetime) -> _Register:
    url = config.database_url()
    if not url:
        raise _RegisterUnknown("no DATABASE_URL")
    try:
        engine = db.make_engine(url)
        try:
            with engine.connect() as conn:
                return _query_register(conn, now)
        finally:
            engine.dispose()
    except Exception as exc:
        # A driver error may quote the connection string with its password.
        raise _RegisterUnknown(f"database error {type(exc).__name__}") from None


def _query_register(conn: Connection, now: datetime.datetime) -> _Register:
    lines, certs = db.device_lines.c, db.issued_certificates.c
    line_of = {
        row.id: (row.subject_id, row.scope)
        for row in conn.execute(
            select(lines.id, lines.subject_id, lines.scope).where(lines.revoked_at.is_(None))
        )
    }
    newest: dict[str, _Device] = {}
    for row in conn.execute(
        select(certs.line_id, certs.not_before, certs.not_after, certs.created_at)
    ):
        not_before = _aware(row.not_before)
        if row.line_id in line_of and (
            row.line_id not in newest or not_before > newest[row.line_id].not_before
        ):
            newest[row.line_id] = _Device(not_before, _aware(row.not_after), _aware(row.created_at))
    revoked = {
        (row.subject_id, row.scope): row.revoked_at
        for row in conn.execute(
            select(
                db.revoked_identities.c.subject_id,
                db.revoked_identities.c.scope,
                db.revoked_identities.c.revoked_at,
            )
        )
    }
    devices = []
    for line_id, device in newest.items():
        identity = line_of[line_id]
        # DbTokenStore._active: revoked up to revoked_at, without a time for good.
        if identity in revoked and (
            revoked[identity] is None or device.not_before <= _aware(revoked[identity])
        ):
            continue
        if device.not_after > now:
            devices.append(device)
    installed_at = conn.execute(
        select(db.certificate_register_state.c.installed_at).where(
            db.certificate_register_state.c.id == 1
        )
    ).scalar()
    inventory = db.infra_certificates.c
    started = conn.execute(
        select(inventory.fingerprint, inventory.recorded_at).where(inventory.name == "root")
    ).first()
    return _Register(
        devices,
        installed_at and _aware(installed_at),
        started and started.fingerprint,
        started and _aware(started.recorded_at),
    )


def _aware(at: datetime.datetime) -> datetime.datetime:
    return at.replace(tzinfo=datetime.timezone.utc)  # the register stores naive UTC


@dataclass(frozen=True)
class _Secret:
    what: str
    env: str  # read from <env>_FILE, else <env>
    read: Callable[[], bytes | None]
    prompt: str


_ROOT = _Secret(
    "root passphrase", "CA_ROOT_PASSPHRASE", config.root_passphrase, "Root CA passphrase: "
)
_NEXT_ROOT = _Secret(
    "passphrase of the new root",
    "CA_NEXT_ROOT_PASSPHRASE",
    config.next_root_passphrase,
    "New root CA passphrase: ",
)


def _passphrase(secret: _Secret, confirm: bool = False) -> bytes:
    """`secret` from its file or env var, else asked on the terminal (twice with
    `confirm`), else the next line of stdin."""
    try:
        passphrase = secret.read()
    except OSError as exc:
        raise _Refused(f"cannot read the {secret.what}: {exc}") from exc
    if not passphrase:
        passphrase = _ask_passphrase(secret.prompt, confirm)
    if not passphrase:
        raise _Refused(
            f"no {secret.what} — none in {secret.env}_FILE or {secret.env}, none entered on "
            "the terminal or as the next line of stdin"
        )
    return passphrase


def _ask_passphrase(prompt: str = "Root CA passphrase: ", confirm: bool = False) -> bytes:
    if sys.stdin.isatty():
        try:
            passphrase = getpass.getpass(prompt).encode()
            again = getpass.getpass("Repeat it: ").encode() if confirm and passphrase else None
        except EOFError:
            return b""
        if again is not None and again != passphrase:
            raise _Refused("the two passphrases entered differ")
        return passphrase
    return sys.stdin.readline().rstrip("\r\n").encode()


def _name_and_end(cert: x509.Certificate) -> str:
    return f"{pki.read_identity(cert)[0]} (notAfter {cert.not_valid_after_utc.isoformat()})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="Operator commands of the ca-issuer PKI."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "status",
        help="show root, current and retired intermediates with their end and where a root "
        f"renewal stands (exit 0 ok, 1 fewer than {pki.ROOT_WARN_DAYS} days left for the root "
        f"or {pki.EXPIRY_WARN_DAYS} for an intermediate, a retired entry the boot skips or an "
        "old root expired before finish, 3 expired, unreadable or a renewal step stopped part "
        "way)",
    )
    rotate_parser = commands.add_parser(
        "rotate-intermediates",
        help="issue new intermediates for all scopes under the same root; "
        "the replaced ones stay trusted until they expire",
    )
    rotate_parser.add_argument(
        "--compromised",
        action="append",
        choices=pki.SCOPES,
        default=[],
        metavar="SCOPE",
        help=f"a scope whose intermediate key leaked ({', '.join(pki.SCOPES)}; repeatable): "
        "neither its replaced intermediate nor an earlier one is renewed or kept in a trust "
        "bundle (revoke its devices too, see the operations docs)",
    )
    root_parser = commands.add_parser(
        "rotate-root",
        help="renew the root without enrolling the clients again: stage, switch, finish "
        "(abort before the switch), see the operations docs",
    )
    steps = root_parser.add_subparsers(dest="step", required=True)
    steps.add_parser(
        "stage",
        help="create the new root beside the current one, which goes on signing; enroll and "
        "renew hand out both",
    )
    steps.add_parser("abort", help="remove the staged new root (only before the switch)")
    switch_parser = steps.add_parser(
        "switch",
        help="make the new root the root: new intermediates under it and a cross certificate "
        "signed by the old root; the old root's key is gone afterwards",
    )
    switch_options = switch_parser.add_mutually_exclusive_group()
    switch_options.add_argument(
        "--compromised",
        action="append",
        choices=pki.SCOPES,
        default=[],
        metavar="SCOPE",
        help=f"a scope whose intermediate key leaked ({', '.join(pki.SCOPES)}; repeatable): "
        "nothing replaced of it stays trusted, and the old root leaves `chain`",
    )
    switch_options.add_argument(
        "--no-cross",
        action="store_true",
        help="no cross certificate, the old root's passphrase is not needed: a client that "
        "trusts only the old root loses the server",
    )
    finish_parser = steps.add_parser(
        "finish",
        help="drop the old root, the cross certificate and the intermediates under the old "
        "root from every bundle, once the register shows no device under the old root",
    )
    finish_parser.add_argument(
        "--force",
        action="store_true",
        help="finish although the register is unknown or shows devices under the old root",
    )
    args = parser.parse_args(argv)
    if args.command == "status":
        return status(config.pki_dir())
    if args.command == "rotate-root":
        return rotate_root(
            config.pki_dir(),
            args.step,
            frozenset(getattr(args, "compromised", ())),
            cross=not getattr(args, "no_cross", False),
            force=getattr(args, "force", False),
        )
    return rotate(config.pki_dir(), frozenset(args.compromised))


if __name__ == "__main__":
    sys.exit(main())
