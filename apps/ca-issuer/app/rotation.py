# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rotation of the scoped intermediates (R-0667) and the steps of a root renewal (R-1021).

rotate_intermediates issues a new intermediate for every scope in pki.SCOPES with the
root key from root.key.enc and moves the one it replaces into <scope>-retired.pem,
which storage.ensure_hierarchy loads as Intermediate.retired: leaves of the earlier
generation still renew and pass the gateway and frps trust bundles until that
intermediate expires. It reads no intermediate key and does not need the issuer, so
it also runs when the issuer no longer starts because an intermediate expired. The
issuer, the gateway and frps take the new hierarchy on their next start.

A root renewal moves the hierarchy from the root R to a new root N in phases
(app.root_rollover): stage_root creates N beside R, abort_root removes it again,
switch_root issues the intermediates under N, signs the cross certificate X with R's key
and makes N the root, finish_root drops R, X and the intermediates under R. They live
here and not in app.root_rollover, which only reads the phase, because they share the
lock and the file writes with rotate_intermediates. Each of them, like the rotation,
checks everything before its first write, replaces every file atomically, and a run
that stopped part way is ended by the same call.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import fcntl
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import pki, root_rollover
from app.root_rollover import CROSS, NEXT_CRT, NEXT_KEY, RETIRED, ROTATE_ROOT, STATE

LOCK_NAME = ".rotate.lock"


class RotationError(Exception):
    """The rotation did not complete; the message says why. Anything found wrong with
    the root, the passphrase or the files read is raised before the first write."""


@dataclass(frozen=True)
class RotatedScope:
    scope: str
    old: x509.Certificate  # the replaced intermediate (retired only while valid)
    new: x509.Certificate


@dataclass(frozen=True)
class SwitchedRoot:
    root: x509.Certificate  # N, now root.crt
    retired_root: x509.Certificate  # R, now root-retired.pem
    cross: x509.Certificate | None  # X, None after --no-cross
    # The scopes this run moved under N; a run that ends a stopped switch lists only those
    # the stopped one had not moved.
    rotated: list[RotatedScope]


def rotate_intermediates(
    pki_dir: Path, passphrase: bytes, compromised: frozenset[str] = frozenset()
) -> list[RotatedScope]:
    """Issue a new intermediate for every scope under root.crt; the replaced ones that
    are still valid go to <scope>-retired.pem, expired entries leave that file. A
    current intermediate of its scope that is not valid yet by this clock stops it
    (RotationError). For a scope in `compromised` nothing replaced stays trusted: its
    retired file ends up empty, whatever it held. A name in `compromised` that is no
    scope is a RotationError before anything is read.
    During a root renewal root.crt is R while N is staged and N after the switch; then
    the retired files also keep the intermediates under R, and with `compromised` R
    leaves `chain` before finish (Switch.drop_retired_root) and the scope goes into
    Switch.compromised. A switch or finish that stopped part way is a RotationError: it
    has to be ended first.
    Holds an exclusive lock on <pki_dir>/.rotate.lock (RotationError if another run
    holds it). Returns one RotatedScope per scope, in pki.SCOPES order."""
    _check_scopes(compromised)
    with _locked(pki_dir):
        return _rotate(pki_dir, passphrase, compromised)


def _rotate(pki_dir: Path, passphrase: bytes, compromised: frozenset[str]) -> list[RotatedScope]:
    state = _state(pki_dir)
    if state.phase in ("switching", "finishing"):
        raise RotationError(refusal(state.phase, "rotate the intermediates"))
    now = pki._now()
    root_cert, root_key = _load_root(pki_dir, passphrase, now)
    roots = (root_cert,) if state.retired_root is None else (root_cert, state.retired_root)
    label = now.strftime("%Y-%m-%d")
    planned = [
        _plan_scope(pki_dir, scope, root_cert, root_key, roots, scope in compromised, now, label)
        for scope in pki.SCOPES
    ]

    # Everything is read and checked; from here on files change. Per scope the order is
    # retired file, key, certificate, chain: the replaced intermediate is in the retired
    # file before anything else changes, so no interruption loses it. An interruption
    # between key and certificate leaves a pair that does not match, and the issuer
    # refuses to start with it (ensure_hierarchy); a second run repairs that, because it
    # reads only <scope>.crt (still the old certificate, retired again) and never the key.
    # The replaced key is overwritten rather than kept: checking the leaves it signed
    # needs only its certificate, and a spare signing key would be risk without a use.
    if compromised and state.switch is not None:
        # Before the retired files: a client that trusts R trusts the intermediates under
        # R that this run drops, so R leaves `chain` from the next boot on; and the scope
        # goes into the record, which the issuer reads to refuse an intermediate under R
        # written back into its retired file.
        new_switch = dataclasses.replace(
            state.switch,
            compromised=tuple(sorted(set(state.switch.compromised) | compromised)),
            drop_retired_root=True,
        )
        if new_switch != state.switch:
            _replace(pki_dir / STATE, new_switch.to_json(), 0o644)
    for rotated, new_key, retired in planned:
        _write_scope(pki_dir, rotated, new_key, retired, root_cert)
    _sync_dir(pki_dir)
    return [rotated for rotated, _, _ in planned]


def stage_root(pki_dir: Path, next_passphrase: bytes) -> x509.Certificate:
    """Create the new root N beside root.crt: root-next.key.enc (0600, encrypted with
    `next_passphrase`, which may equal the one of root.key.enc), then root-next.crt.
    Only while no renewal is under way; a stage that stopped before the certificate is
    overwritten. Needs no root passphrase: N signs itself, root.crt goes on signing as
    before. Returns N."""
    if not next_passphrase:
        raise RotationError("cannot stage: the new root needs a passphrase")
    with _locked(pki_dir):
        state = _state(pki_dir)
        if state.phase != "none":
            raise RotationError(refusal(state.phase, "stage"))
        root_cert = _read_cert(pki_dir / "root.crt")
        new_root, new_key = pki.build_root_ca(label=pki._now().strftime("%Y-%m-%d"))
        if new_root.subject == root_cert.subject:
            # Both are trusted side by side until finish, and clients find an issuer by name.
            raise RotationError(
                f"cannot stage: the new root would be named {pki.read_identity(new_root)[0]!r} "
                "like root.crt; stage on another day"
            )
        _replace(pki_dir / NEXT_KEY, pki.key_to_pem(new_key, next_passphrase), 0o600)
        _replace(pki_dir / NEXT_CRT, pki.cert_to_pem(new_root), 0o644)
        _sync_dir(pki_dir)
        return new_root


def abort_root(pki_dir: Path) -> None:
    """Remove the staged root N: root-next.crt, then root-next.key.enc. Only before the
    switch: the switch overwrites the key of R, from then on only the backup leads back."""
    with _locked(pki_dir):
        if switched := [name for name in (STATE, RETIRED, CROSS) if (pki_dir / name).exists()]:
            raise RotationError(
                f"cannot abort: the switch has run ({', '.join(switched)} exist); after the "
                "switch only the backup of the PKI volume from before it leads back"
            )
        staged = [name for name in (NEXT_CRT, NEXT_KEY) if (pki_dir / name).exists()]
        if not staged:
            raise RotationError("cannot abort: no new root is staged")
        for name in staged:
            _remove(pki_dir / name)
        _sync_dir(pki_dir)


def switch_root(
    pki_dir: Path,
    next_passphrase: bytes,
    root_passphrase: bytes | None,
    compromised: frozenset[str] = frozenset(),
    cross: bool = True,
) -> SwitchedRoot:
    """Make the staged root N the root. Every scope gets a new intermediate under N; the
    replaced one goes to <scope>-retired.pem as in rotate_intermediates, a scope in
    `compromised` keeps nothing replaced and R leaves `chain`. With `cross` the key of R
    (`root_passphrase`) signs X first; without it R's passphrase is not needed, and a
    client that trusts only R loses the server. `compromised` without `cross` is refused:
    a leak puts stage and switch on the same day, so no client has N yet.
    Write order: root-switch.json (the options), root-retired.pem (R), root-cross.pem (X);
    per scope retired file, key, certificate, chain [I(N), N]; root.key.enc, root.crt
    (now N, R's key is gone); root-next.crt and root-next.key.enc removed. A switch that
    stopped part way is ended by the same call with the same options; it skips the
    scopes already under N and needs R's passphrase only while X is missing."""
    _check_scopes(compromised)
    if compromised and not cross:
        raise RotationError(
            "cannot switch: --compromised needs the cross certificate; after a leak stage and "
            "switch run on the same day, and without it no client that has not renewed in "
            "between reaches the server"
        )
    with _locked(pki_dir):
        return _switch(pki_dir, next_passphrase, root_passphrase, compromised, cross)


def _switch(
    pki_dir: Path,
    next_passphrase: bytes,
    root_passphrase: bytes | None,
    compromised: frozenset[str],
    cross: bool,
) -> SwitchedRoot:
    state = _state(pki_dir)
    if state.phase not in ("staged", "switching"):
        raise RotationError(refusal(state.phase, "switch"))
    now = pki._now()
    switch = root_rollover.Switch(now, tuple(sorted(compromised)), cross, bool(compromised))
    if state.switch is not None:
        if (state.switch.compromised, state.switch.cross) != (switch.compromised, switch.cross):
            raise RotationError(
                f"cannot switch: the switch that stopped part way ran with "
                f"{_options(state.switch)}; run it again with exactly these options"
            )
        switch = state.switch
    if not cross and state.cross is not None:
        raise RotationError(
            f"cannot switch: {pki_dir / CROSS} exists, but the switch runs without a cross "
            "certificate; restore the PKI volume from the backup of the last step"
        )

    # Until root-retired.pem is written root.crt is R; until root-next.crt is removed it
    # is N, and root.crt is N from before that.
    root_crt = pki_dir / "root.crt"
    old_root = state.retired_root or _read_cert(root_crt)
    new_root = state.next_root or _read_cert(root_crt)
    if _spki(new_root) == _spki(old_root):
        raise RotationError(
            f"cannot switch: no new root beside {_root_name(old_root)}; restore the PKI "
            "volume from the backup of the last step"
        )
    # root.crt becomes N and root.key.enc its key: a file that is no root would leave the
    # PKI without one, the key of R gone.
    if problem := pki.root_problem(new_root):
        raise RotationError(
            f"cannot switch: the new root {_root_name(new_root)} is no root, {problem}; "
            f"remove it with: {ROTATE_ROOT} abort, then stage again"
        )
    next_key_pem = _read_bytes(pki_dir / NEXT_KEY)
    new_key = _decrypt(pki_dir / NEXT_KEY, next_key_pem, next_passphrase, new_root)
    start, end = new_root.not_valid_before_utc, new_root.not_valid_after_utc
    if not start <= now < end:
        raise RotationError(
            f"cannot switch: the new root is not valid now (notBefore {start.isoformat()}, "
            f"notAfter {end.isoformat()}); check the host clock (NTP)"
        )
    cross_cert = state.cross
    if cross_cert is not None:
        if problem := pki.cross_problem(cross_cert, new_root, old_root):
            raise RotationError(
                f"{pki_dir / CROSS}: {problem}; restore the PKI volume from the backup of the "
                "last step"
            )
    elif cross:
        cross_cert = _cross(pki_dir, new_root, old_root, root_passphrase, now)

    label = now.strftime("%Y-%m-%d")
    roots = (new_root, old_root)
    planned = []
    moved: list[tuple[str, x509.Certificate]] = []
    for scope in pki.SCOPES:
        current = _read_cert(pki_dir / f"{scope}.crt")
        if pki.intermediate_problem(current, scope, new_root) is None and _is_key_of(
            pki_dir / f"{scope}.key", current
        ):
            moved.append((scope, current))  # by the run that stopped
            continue
        planned.append(
            _plan_scope(pki_dir, scope, new_root, new_key, roots, scope in compromised, now, label)
        )

    # Everything is read and checked; from here on files change. The record and R come
    # first, so a run that stops later knows the options and which root was R; X before
    # root.key.enc, the only copy of R's key, is overwritten.
    if state.switch is None:
        _replace(pki_dir / STATE, switch.to_json(), 0o644)
    if state.retired_root is None:
        _replace(pki_dir / RETIRED, pki.cert_to_pem(old_root), 0o644)
    if cross_cert is not None and state.cross is None:
        _replace(pki_dir / CROSS, pki.cert_to_pem(cross_cert), 0o644)
    _sync_dir(pki_dir)
    for rotated, key, retired in planned:
        _write_scope(pki_dir, rotated, key, retired, new_root)
    for scope, current in moved:
        _replace(pki_dir / f"{scope}-chain.pem", pki.chain_pem(current, new_root), 0o644)
    _sync_dir(pki_dir)
    _replace(pki_dir / "root.key.enc", next_key_pem, 0o600)
    _replace(root_crt, pki.cert_to_pem(new_root), 0o644)
    _sync_dir(pki_dir)
    for name in (NEXT_CRT, NEXT_KEY):
        _remove(pki_dir / name)
    _sync_dir(pki_dir)
    return SwitchedRoot(new_root, old_root, cross_cert, [r for r, _, _ in planned])


def finish_root(pki_dir: Path) -> None:
    """End a renewal after the switch: the retired files keep only intermediates under
    N, then root-cross.pem, root-retired.pem and last root-switch.json go. R, X and the
    intermediates under R are then in no bundle. Whether a device still depends on R is
    the caller's check (the CLI asks the register). Needs no passphrase; a finish that
    stopped part way is ended by the same call."""
    with _locked(pki_dir):
        state = _state(pki_dir)
        if state.phase not in ("switched", "finishing"):
            raise RotationError(refusal(state.phase, "finish"))
        root_cert = _read_cert(pki_dir / "root.crt")
        old_roots = () if state.retired_root is None else (state.retired_root,)
        if old_roots and _spki(old_roots[0]) == _spki(root_cert):
            raise RotationError(
                f"cannot finish: root.crt is the root of {RETIRED}; restore the PKI volume "
                "from the backup of the last step"
            )
        kept = {
            scope: _retired_under(pki_dir / f"{scope}-retired.pem", scope, root_cert, old_roots)
            for scope in pki.SCOPES
        }

        for scope, certs in kept.items():
            _replace(pki_dir / f"{scope}-retired.pem", pki.chain_pem(*certs), 0o644)
        _sync_dir(pki_dir)
        _remove(pki_dir / CROSS)
        _remove(pki_dir / RETIRED)
        _sync_dir(pki_dir)
        _remove(pki_dir / STATE)
        _sync_dir(pki_dir)


def _root_name(cert: x509.Certificate) -> str:
    return repr(pki.read_identity(cert)[0])


def refusal(phase: str, action: str) -> str:
    """Why `action` does not run in renewal `phase`, with the command that moves the
    renewal on; the CLI says it before asking for a passphrase."""
    reason = {
        "none": f"no new root is staged; stage one with: {ROTATE_ROOT} stage",
        "staged": f"a new root is staged; switch to it, or remove it with: {ROTATE_ROOT} abort",
        "switching": (
            f"a root switch stopped part way; end it with: {ROTATE_ROOT} switch, "
            "with the same options"
        ),
        "switched": (
            f"the root switch has run; end the renewal with: {ROTATE_ROOT} finish, once no "
            "device depends on the old root"
        ),
        "finishing": f"a root finish stopped part way; end it with: {ROTATE_ROOT} finish",
    }[phase]
    return f"cannot {action}: {reason}"


def _options(switch: root_rollover.Switch) -> str:
    options = [f"--compromised {scope}" for scope in switch.compromised]
    if not switch.cross:
        options.append("--no-cross")
    return " ".join(options) or "no options"


def _check_scopes(compromised: frozenset[str]) -> None:
    if unknown := sorted(compromised - set(pki.SCOPES)):
        raise RotationError(
            f"no such scope: {', '.join(unknown)} (scopes: {', '.join(pki.SCOPES)})"
        )


@contextlib.contextmanager
def _locked(pki_dir: Path) -> Iterator[None]:
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
        yield
    finally:
        os.close(lock_fd)  # releases the lock


def _state(pki_dir: Path) -> root_rollover.State:
    try:
        return root_rollover.load_state(pki_dir)
    except root_rollover.RolloverError as exc:
        raise RotationError(str(exc)) from exc


def _plan_scope(
    pki_dir: Path,
    scope: str,
    root_cert: x509.Certificate,
    root_key: ec.EllipticCurvePrivateKey,
    roots: tuple[x509.Certificate, ...],
    compromised: bool,
    now: datetime.datetime,
    label: str,
) -> tuple[RotatedScope, ec.EllipticCurvePrivateKey, list[x509.Certificate]]:
    """The new intermediate of `scope` under `root_cert` and what its retired file holds
    then; `roots` are the roots an intermediate kept as retired may be under."""
    crt = pki_dir / f"{scope}.crt"
    old = _read_cert(crt)
    if compromised:
        # Its key may sign for someone else: neither it nor a predecessor stays
        # trusted, so the clock (which only decides what is kept) does not matter.
        new_cert, new_key = pki.build_intermediate_ca(scope, root_cert, root_key, label=label)
        return RotatedScope(scope, old, new_cert), new_key, []
    # An intermediate is valid from its issuing, so one not valid yet means this clock
    # is behind the one that issued it. Replaced under it, the intermediate would not
    # be kept as retired (it is not valid now), and once the clock is right nothing
    # would trust the leaves it signed: the cure is the clock (storage.CLOCK_HINT).
    # A certificate that is no intermediate of this scope is never kept as retired
    # (_retired_after), so the clock costs it nothing and the rotation replaces it.
    if now < old.not_valid_before_utc and pki.intermediate_problem_among(old, scope, roots) is None:
        raise RotationError(
            f"{crt}: {pki.read_identity(old)[0]!r} is not valid before "
            f"{old.not_valid_before_utc.isoformat()}, the host clock says "
            f"{now.isoformat()}; check the host clock (NTP), it is behind the issuing "
            "of this intermediate; under this clock the rotation changes nothing"
        )
    retired = _retired_after(pki_dir / f"{scope}-retired.pem", scope, old, roots, now)
    new_cert, new_key = pki.build_intermediate_ca(scope, root_cert, root_key, label=label)
    return RotatedScope(scope, old, new_cert), new_key, retired


def _write_scope(
    pki_dir: Path,
    rotated: RotatedScope,
    new_key: ec.EllipticCurvePrivateKey,
    retired: list[x509.Certificate],
    root_cert: x509.Certificate,
) -> None:
    scope = rotated.scope
    _replace(pki_dir / f"{scope}-retired.pem", pki.chain_pem(*retired), 0o644)
    _replace(pki_dir / f"{scope}.key", pki.key_to_pem(new_key), 0o600)
    _replace(pki_dir / f"{scope}.crt", pki.cert_to_pem(rotated.new), 0o644)
    _replace(pki_dir / f"{scope}-chain.pem", pki.chain_pem(rotated.new, root_cert), 0o644)


def _cross(
    pki_dir: Path,
    new_root: x509.Certificate,
    old_root: x509.Certificate,
    root_passphrase: bytes | None,
    now: datetime.datetime,
) -> x509.Certificate:
    start, end = old_root.not_valid_before_utc, old_root.not_valid_after_utc
    if not start <= now < end:
        raise RotationError(
            f"cannot switch: root.crt is not valid now (notBefore {start.isoformat()}, "
            f"notAfter {end.isoformat()}) and cannot sign the cross certificate; switch "
            "with --no-cross, then a client that trusts only this root loses the server"
        )
    if not root_passphrase:
        raise RotationError(
            "cannot switch: the cross certificate needs the passphrase of root.key.enc; "
            "without it switch with --no-cross, then a client that trusts only this root "
            "loses the server"
        )
    root_key_enc = pki_dir / "root.key.enc"
    old_key = _decrypt(root_key_enc, _read_bytes(root_key_enc), root_passphrase, old_root)
    return pki.build_cross_cert(new_root, old_root, old_key)


def _load_root(
    pki_dir: Path, passphrase: bytes, now: datetime.datetime
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    root_crt = pki_dir / "root.crt"
    root_cert = _read_cert(root_crt)
    try:
        root_key = pki.key_from_pem((pki_dir / "root.key.enc").read_bytes(), passphrase)
    except Exception as exc:  # a wrong passphrase raises ValueError or TypeError
        raise RotationError("wrong passphrase or unreadable root key") from exc
    if _spki(root_cert) != _spki(root_key):
        raise RotationError(f"root.key.enc is not the private key of {root_crt}")
    start, end = root_cert.not_valid_before_utc, root_cert.not_valid_after_utc
    if not start <= now < end:
        raise RotationError(
            f"{root_crt} is not valid now (notBefore {start.isoformat()}, notAfter "
            f"{end.isoformat()}); no intermediate can be issued under it"
        )
    return root_cert, root_key


def _decrypt(
    path: Path, pem: bytes, passphrase: bytes, cert: x509.Certificate
) -> ec.EllipticCurvePrivateKey:
    try:
        key = pki.key_from_pem(pem, passphrase)
    except Exception as exc:  # a wrong passphrase raises ValueError or TypeError
        raise RotationError(f"wrong passphrase or unreadable key {path}") from exc
    if _spki(key) != _spki(cert):
        raise RotationError(f"{path} is not the private key of {_root_name(cert)}")
    return key


def _is_key_of(path: Path, cert: x509.Certificate) -> bool:
    try:
        return _spki(pki.key_from_pem(path.read_bytes())) == _spki(cert)
    except Exception:  # missing, unreadable or no key: not the key of `cert`
        return False


def _spki(holder: x509.Certificate | ec.EllipticCurvePrivateKey) -> bytes:
    return holder.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RotationError(f"cannot read {path}: {exc}") from exc


def _read_cert(path: Path) -> x509.Certificate:
    try:
        return pki.cert_from_pem(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RotationError(f"cannot read {path}: {exc}") from exc


def _read_retired(path: Path) -> list[x509.Certificate]:
    try:
        data = path.read_bytes() if path.exists() else b""
        return x509.load_pem_x509_certificates(data) if data.strip() else []
    except (OSError, ValueError) as exc:
        raise RotationError(f"cannot read {path} as PEM certificates: {exc}") from exc


def _retired_after(
    path: Path,
    scope: str,
    old: x509.Certificate,
    roots: tuple[x509.Certificate, ...],
    now: datetime.datetime,
) -> list[x509.Certificate]:
    """What the retired file `path` holds after the rotation, newest first and each
    once: `old` if it is an intermediate of `scope` under one of `roots`
    (pki.intermediate_problem) and valid now, and the file's entries that have not
    expired. An `old` that is not one (a restore with the scopes mixed up, a foreign
    certificate) is replaced without being kept: the rotation is also the way to replace
    a wrong <scope>.crt, and kept it would be an entry the boot skips and the next
    rotation stops at. An entry of the file that is not an intermediate of `scope` under
    one of `roots` is a RotationError: the boot skips such an entry unattended, with a
    WARNING; a rotation that rewrites the file would either carry it on or drop it
    silently, and that is the operator's call."""
    earlier = _read_retired(path)
    for cert in earlier:
        if problem := pki.intermediate_problem_among(cert, scope, roots):
            name = pki.read_identity(cert)[0]
            raise RotationError(
                f"{path}: {name!r} is not a retired {scope!r} intermediate, {problem}; "
                "correct the file (the issuer skips such an entry on boot), then rotate again"
            )

    keep = [c for c in earlier if now < c.not_valid_after_utc]
    if (
        pki.intermediate_problem_among(old, scope, roots) is None
        and old.not_valid_before_utc <= now < old.not_valid_after_utc
    ):
        keep.append(old)
    der = serialization.Encoding.DER
    unique = {c.public_bytes(der): c for c in keep}
    return sorted(unique.values(), key=lambda c: c.not_valid_before_utc, reverse=True)


def _retired_under(
    path: Path,
    scope: str,
    root: x509.Certificate,
    old_roots: tuple[x509.Certificate, ...],
) -> list[x509.Certificate]:
    """The entries of the retired file `path` under `root`, for finish: an entry under one
    of `old_roots` leaves, any other entry is a RotationError, as in _retired_after."""
    keep = []
    for cert in _read_retired(path):
        if pki.intermediate_problem(cert, scope, root) is None:
            keep.append(cert)
        elif problem := pki.intermediate_problem_among(cert, scope, (root, *old_roots)):
            name = pki.read_identity(cert)[0]
            raise RotationError(
                f"{path}: {name!r} is not a retired {scope!r} intermediate, {problem}; "
                "correct the file (the issuer skips such an entry on boot), then finish again"
            )
    return keep


def _sync_dir(pki_dir: Path) -> None:
    """fsync the directory, so the renames and removals so far are on disk before the
    next step; the order of the steps is what a stopped run is ended by."""
    try:
        dir_fd = os.open(pki_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise RotationError(f"cannot sync {pki_dir}: {exc}") from exc


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
            "run it again with the same options once the cause is fixed"
        ) from exc


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise RotationError(
            f"cannot remove {path}: {exc}; the rotation stopped part way, "
            "run it again with the same options once the cause is fixed"
        ) from exc
