# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operator CLI of the ca-issuer — run in a one-off container of the service:

    docker compose run --rm --no-deps ca-issuer python -m app.cli status
    docker compose run --rm --no-deps ca-issuer python -m app.cli rotate-intermediates

``run``, not ``exec``: it also works while the issuer is stopped or no longer starts
(an expired intermediate), and the entrypoint drops it to the ``app`` user like the
service. ``status`` reads certificates only. ``rotate-intermediates`` needs the root
passphrase: from the secret file or env var the service reads, else asked on the
terminal, else the first line of stdin — never as an argument, which ``ps`` shows.

Listings go to stdout, errors to stderr."""

from __future__ import annotations

import argparse
import datetime
import getpass
import sys
from pathlib import Path

from cryptography import x509

from app import config, pki, rotation

# status: 0 all fine, 1 the root or a current intermediate has fewer than
# pki.EXPIRY_WARN_DAYS left, 3 one of them is not valid now or not readable (2 is
# argparse's usage error). Retired intermediates never raise it by their time: they run
# out by design. An entry of a retired file that the boot skips with a WARNING (not an
# intermediate of its scope under the root, pki.intermediate_problem) is 1, marked SKIPPED.
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


def status(pki_dir: Path) -> int:
    """Print root.crt, then per scope <scope>.crt and the entries of <scope>-retired.pem,
    one line each; return the exit code (see OK, WARN, BAD)."""
    now = pki._now()
    worst = _show_current("root", pki_dir / "root.crt", now)
    try:
        root: x509.Certificate | None = pki.cert_from_pem((pki_dir / "root.crt").read_bytes())
    except (OSError, ValueError):
        root = None  # shown as unreadable above; the retired entries go unchecked
    for scope in pki.SCOPES:
        worst = max(worst, _show_current(scope, pki_dir / f"{scope}.crt", now))
        worst = max(worst, _show_retired(scope, pki_dir / f"{scope}-retired.pem", now, root))
    return worst


def _show_current(role: str, path: Path, now: datetime.datetime) -> int:
    try:
        cert = pki.cert_from_pem(path.read_bytes())
    except (OSError, ValueError) as exc:
        return _unreadable(role, path, exc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        print(_line(role, cert, now))
        return BAD
    if pki.days_left(cert, now) < pki.EXPIRY_WARN_DAYS:  # the boot WARNING's rule
        print(f"{_line(role, cert, now)}  WARNING")
        return WARN
    print(_line(role, cert, now))
    return OK


def _show_retired(
    scope: str, path: Path, now: datetime.datetime, root: x509.Certificate | None
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
        if root is not None and (problem := pki.intermediate_problem(cert, scope, root)):
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


def _ask_passphrase() -> bytes:
    if sys.stdin.isatty():
        try:
            return getpass.getpass("Root CA passphrase: ").encode()
        except EOFError:
            return b""
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
        help="show root, current and retired intermediates with their end (exit 0 ok, "
        f"1 fewer than {pki.EXPIRY_WARN_DAYS} days left or a retired entry the boot skips, "
        "3 expired or unreadable)",
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
    args = parser.parse_args(argv)
    if args.command == "status":
        return status(config.pki_dir())
    return rotate(config.pki_dir(), frozenset(args.compromised))


if __name__ == "__main__":
    sys.exit(main())
