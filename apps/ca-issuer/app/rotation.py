# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rotation of the scoped intermediates under the same root (R-0667).

rotate_intermediates issues a new intermediate for every scope in pki.SCOPES with the
root key from root.key.enc and moves the one it replaces into <scope>-retired.pem,
which storage.ensure_hierarchy loads as Intermediate.retired: leaves of the earlier
generation still renew and pass the gateway and frps trust bundles until that
intermediate expires. It reads no intermediate key and does not need the issuer, so
it also runs when the issuer no longer starts because an intermediate expired. The
issuer, the gateway and frps take the new hierarchy on their next start.
"""

from __future__ import annotations

import contextlib
import datetime
import fcntl
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import pki

LOCK_NAME = ".rotate.lock"


class RotationError(Exception):
    """The rotation did not complete; the message says why. Anything found wrong with
    the root, the passphrase or the files read is raised before the first write."""


@dataclass(frozen=True)
class RotatedScope:
    scope: str
    old: x509.Certificate  # the replaced intermediate (retired only while valid)
    new: x509.Certificate


def rotate_intermediates(pki_dir: Path, passphrase: bytes) -> list[RotatedScope]:
    """Issue a new intermediate for every scope under root.crt; the replaced ones that
    are still valid go to <scope>-retired.pem, expired entries leave that file. Holds
    an exclusive lock on <pki_dir>/.rotate.lock (RotationError if another run holds
    it). Returns one RotatedScope per scope, in pki.SCOPES order."""
    lock_path = pki_dir / LOCK_NAME
    try:
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise RotationError(f"cannot open {lock_path}: {exc}") from exc
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RotationError("another rotation is running") from None
        return _rotate(pki_dir, passphrase)
    finally:
        os.close(lock_fd)  # releases the lock


def _rotate(pki_dir: Path, passphrase: bytes) -> list[RotatedScope]:
    now = pki._now()
    root_cert, root_key = _load_root(pki_dir, passphrase, now)
    label = now.strftime("%Y-%m-%d")
    planned: list[tuple[RotatedScope, ec.EllipticCurvePrivateKey, list[x509.Certificate]]] = []
    for scope in pki.SCOPES:
        old = _read_cert(pki_dir / f"{scope}.crt")
        retired = _retired_after(pki_dir / f"{scope}-retired.pem", scope, old, root_cert, now)
        new_cert, new_key = pki.build_intermediate_ca(scope, root_cert, root_key, label=label)
        planned.append((RotatedScope(scope, old, new_cert), new_key, retired))

    # Everything is read and checked; from here on files change. Per scope the order is
    # retired file, key, certificate, chain: the replaced intermediate is in the retired
    # file before anything else changes, so no interruption loses it. An interruption
    # between key and certificate leaves a pair that does not match, and the issuer
    # refuses to start with it (ensure_hierarchy); a second run repairs that, because it
    # reads only <scope>.crt (still the old certificate, retired again) and never the key.
    # The replaced key is overwritten rather than kept: checking the leaves it signed
    # needs only its certificate, and a spare signing key would be risk without a use.
    for rotated, new_key, retired in planned:
        scope = rotated.scope
        _replace(pki_dir / f"{scope}-retired.pem", pki.chain_pem(*retired), 0o644)
        _replace(pki_dir / f"{scope}.key", pki.key_to_pem(new_key), 0o600)
        _replace(pki_dir / f"{scope}.crt", pki.cert_to_pem(rotated.new), 0o644)
        _replace(pki_dir / f"{scope}-chain.pem", pki.chain_pem(rotated.new, root_cert), 0o644)
    try:
        dir_fd = os.open(pki_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise RotationError(f"cannot sync {pki_dir}: {exc}") from exc
    return [rotated for rotated, _, _ in planned]


def _load_root(
    pki_dir: Path, passphrase: bytes, now: datetime.datetime
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    root_crt = pki_dir / "root.crt"
    root_cert = _read_cert(root_crt)
    try:
        root_key = pki.key_from_pem((pki_dir / "root.key.enc").read_bytes(), passphrase)
    except Exception as exc:  # a wrong passphrase raises ValueError or TypeError
        raise RotationError("wrong passphrase or unreadable root key") from exc
    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    der = serialization.Encoding.DER
    if root_cert.public_key().public_bytes(der, spki) != root_key.public_key().public_bytes(
        der, spki
    ):
        raise RotationError(f"root.key.enc is not the private key of {root_crt}")
    start, end = root_cert.not_valid_before_utc, root_cert.not_valid_after_utc
    if not start <= now < end:
        raise RotationError(
            f"{root_crt} is not valid now (notBefore {start.isoformat()}, notAfter "
            f"{end.isoformat()}); no intermediate can be issued under it"
        )
    return root_cert, root_key


def _read_cert(path: Path) -> x509.Certificate:
    try:
        return pki.cert_from_pem(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RotationError(f"cannot read {path}: {exc}") from exc


def _retired_after(
    path: Path,
    scope: str,
    old: x509.Certificate,
    root: x509.Certificate,
    now: datetime.datetime,
) -> list[x509.Certificate]:
    """What the retired file `path` holds after the rotation, newest first and each
    once: `old` if the root signed it and it is valid now, and the file's entries that
    have not expired. An entry that is not an intermediate of `scope` under the root
    (pki.intermediate_problem) is a RotationError: the boot skips such an entry
    unattended, with a WARNING; a rotation that rewrites the file would either carry it
    on or drop it silently, and that is the operator's call."""
    earlier: list[x509.Certificate] = []
    try:
        data = path.read_bytes() if path.exists() else b""
        if data.strip():
            earlier = x509.load_pem_x509_certificates(data)
    except (OSError, ValueError) as exc:
        raise RotationError(f"cannot read {path} as PEM certificates: {exc}") from exc
    for cert in earlier:
        if problem := pki.intermediate_problem(cert, scope, root):
            name = pki.read_identity(cert)[0]
            raise RotationError(
                f"{path}: {name!r} is not a retired {scope!r} intermediate, {problem}; "
                "correct the file (the issuer skips such an entry on boot), then rotate again"
            )

    keep = [c for c in earlier if now < c.not_valid_after_utc]
    if _signed_by(old, root) and old.not_valid_before_utc <= now < old.not_valid_after_utc:
        keep.append(old)
    der = serialization.Encoding.DER
    unique = {c.public_bytes(der): c for c in keep}
    return sorted(unique.values(), key=lambda c: c.not_valid_before_utc, reverse=True)


def _signed_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    try:
        cert.verify_directly_issued_by(issuer)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def _replace(path: Path, data: bytes, mode: int) -> None:
    """Replace `path` by `data` atomically: a temporary file beside it, fsync, os.replace."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.unlink(missing_ok=True)  # left by an interrupted run; the lock keeps others out
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise RotationError(
            f"cannot write {path}: {exc}; the rotation stopped part way, "
            "run it again once the cause is fixed"
        ) from exc
