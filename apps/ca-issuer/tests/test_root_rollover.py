# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Root renewal (R-1021): stage, abort, switch and finish with the files each leaves,
the refused transitions changing nothing, and a transition that stopped after any of
its writes ended by running it again."""

import datetime
import errno
import hashlib
import json
import os
import stat

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from app import pki, root_rollover, rotation, storage
from app.root_rollover import CROSS, NEXT_CRT, NEXT_KEY, RETIRED, STATE

PW = b"pw"  # root.key.enc of the old root R
NEXT_PW = b"next-pw"  # root-next.key.enc of the new root N, root.key.enc after the switch


@pytest.fixture
def now(monkeypatch):
    """One PKI clock for the whole test, so every label has the same date."""
    fixed = pki._now()
    monkeypatch.setattr(pki, "_now", lambda: fixed)
    return fixed


def _at(monkeypatch, days_ago: float, run):
    then = pki._now() - datetime.timedelta(days=days_ago)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        return run()


def _cert(pki_dir, name: str) -> x509.Certificate:
    return pki.cert_from_pem((pki_dir / name).read_bytes())


def _certs(pki_dir, name: str) -> list[x509.Certificate]:
    data = (pki_dir / name).read_bytes()
    return x509.load_pem_x509_certificates(data) if data.strip() else []


def _snapshot(pki_dir) -> dict[str, str]:
    """sha256 of every file in pki_dir but the lock file, which every transition leaves."""
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in pki_dir.iterdir()
        if p.name != rotation.LOCK_NAME
    }


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _spki(holder) -> bytes:
    return holder.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _phase(pki_dir) -> str:
    return root_rollover.load_state(pki_dir).phase


def _staged(pki_dir) -> tuple[dict[str, storage.Intermediate], x509.Certificate]:
    """A booted hierarchy under R with N staged: (intermediates under R, R)."""
    before = storage.ensure_hierarchy(pki_dir, PW)
    old_root = _cert(pki_dir, "root.crt")
    rotation.stage_root(pki_dir, NEXT_PW)
    return before, old_root


def _device_leaf(inter_cert, inter_key) -> x509.Certificate:
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agent-01")]))
        .sign(key, hashes.SHA256())
    )
    spec = pki.LeafSpec(
        lifetime_days=30, subject_cn="agent-01", scope="tunnel", dns_names=("agent-01",)
    )
    return pki.sign_leaf(csr, inter_cert, inter_key, spec)


def _verify(leaf, intermediates, *anchors) -> list[x509.Certificate]:
    at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    verifier = PolicyBuilder().store(Store(list(anchors))).time(at).build_client_verifier()
    return verifier.verify(leaf, intermediates).chain


def _assert_switched(pki_dir, old_root, new_root, before, compromised=(), cross=True):
    """The files after a switch from R (`old_root`) to N (`new_root`); `before` are the
    intermediates under R."""
    assert _cert(pki_dir, "root.crt") == new_root
    key_pem = (pki_dir / "root.key.enc").read_bytes()
    assert _spki(pki.key_from_pem(key_pem, NEXT_PW)) == _spki(new_root)
    with pytest.raises((ValueError, TypeError)):
        pki.key_from_pem(key_pem, PW)  # R's key is gone
    assert _cert(pki_dir, RETIRED) == old_root
    assert not (pki_dir / NEXT_CRT).exists() and not (pki_dir / NEXT_KEY).exists()
    record = json.loads((pki_dir / STATE).read_bytes())
    assert record["compromised"] == sorted(compromised)
    assert record["cross"] is cross
    assert record["drop_retired_root"] is bool(compromised)
    if cross:
        assert pki.cross_problem(_cert(pki_dir, CROSS), new_root, old_root) is None
    else:
        assert not (pki_dir / CROSS).exists()
    for scope in pki.SCOPES:
        inter = _cert(pki_dir, f"{scope}.crt")
        assert pki.intermediate_problem(inter, scope, new_root) is None
        key = pki.key_from_pem((pki_dir / f"{scope}.key").read_bytes())
        assert _spki(key) == _spki(inter)
        assert _certs(pki_dir, f"{scope}-chain.pem") == [inter, new_root]
        retired = [] if scope in compromised else [before[scope].cert]
        assert _certs(pki_dir, f"{scope}-retired.pem") == retired
    for name, mode in [("root.key.enc", 0o600), ("root.crt", 0o644), (RETIRED, 0o644)]:
        assert _mode(pki_dir / name) == mode, name
    assert _phase(pki_dir) == "switched"


def _failing(monkeypatch, target: str):
    """Make the write (os.replace) or the removal (os.unlink) of `target` fail."""
    real_replace, real_unlink = os.replace, os.unlink

    def replace(src, dst):
        if os.path.basename(dst) == target:
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        real_replace(src, dst)

    def unlink(path, *args, **kwargs):
        if os.path.basename(path) == target:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "unlink", unlink)


# --- stage and abort ---------------------------------------------------------


def test_stage_puts_the_new_root_beside_the_old_one(now, tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    before = _snapshot(tmp_path)

    new_root = rotation.stage_root(tmp_path, NEXT_PW)

    assert pki.read_identity(new_root)[0] == f"AdminHelper Root CA {now:%Y-%m-%d}"
    assert _cert(tmp_path, NEXT_CRT) == new_root
    key = pki.key_from_pem((tmp_path / NEXT_KEY).read_bytes(), NEXT_PW)
    assert _spki(key) == _spki(new_root)
    assert _mode(tmp_path / NEXT_KEY) == 0o600 and _mode(tmp_path / NEXT_CRT) == 0o644
    after = _snapshot(tmp_path)
    assert {k: v for k, v in after.items() if k not in (NEXT_CRT, NEXT_KEY)} == before
    assert _phase(tmp_path) == "staged"
    # R still signs: the issuer boots and a rotation stays under R.
    assert set(storage.ensure_hierarchy(tmp_path, None)) == set(pki.SCOPES)


def test_stage_is_refused_twice_and_without_a_passphrase(now, tmp_path):
    _staged(tmp_path)
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match="cannot stage: a new root is staged"):
        rotation.stage_root(tmp_path, NEXT_PW)
    with pytest.raises(rotation.RotationError, match="needs a passphrase"):
        rotation.stage_root(tmp_path, b"")

    assert _snapshot(tmp_path) == before


def test_a_stage_that_stopped_before_the_certificate_is_staged_again(monkeypatch, now, tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    with monkeypatch.context() as m:
        _failing(m, NEXT_CRT)
        with pytest.raises(rotation.RotationError, match=r"root-next\.crt"):
            rotation.stage_root(tmp_path, NEXT_PW)

    assert (tmp_path / NEXT_KEY).exists() and not (tmp_path / NEXT_CRT).exists()
    assert _phase(tmp_path) == "none"
    new_root = rotation.stage_root(tmp_path, NEXT_PW)
    key = pki.key_from_pem((tmp_path / NEXT_KEY).read_bytes(), NEXT_PW)
    assert _spki(key) == _spki(new_root)


def test_abort_leaves_the_files_as_before_the_stage(now, tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    before = _snapshot(tmp_path)
    rotation.stage_root(tmp_path, NEXT_PW)

    rotation.abort_root(tmp_path)

    assert _snapshot(tmp_path) == before
    with pytest.raises(rotation.RotationError, match="cannot abort: no new root is staged"):
        rotation.abort_root(tmp_path)


def test_abort_removes_a_certificate_left_without_its_key(now, tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    before = _snapshot(tmp_path)
    rotation.stage_root(tmp_path, NEXT_PW)
    (tmp_path / NEXT_KEY).unlink()
    with pytest.raises(rotation.RotationError, match="no key root-next.key.enc"):
        rotation.switch_root(tmp_path, NEXT_PW, PW)

    rotation.abort_root(tmp_path)

    assert _snapshot(tmp_path) == before


# --- switch ------------------------------------------------------------------


def test_switch_moves_the_hierarchy_to_the_new_root(now, tmp_path):
    before, old_root = _staged(tmp_path)
    new_root = _cert(tmp_path, NEXT_CRT)
    old_leaf = _device_leaf(before["tunnel"].cert, before["tunnel"].key)

    switched = rotation.switch_root(tmp_path, NEXT_PW, PW)

    _assert_switched(tmp_path, old_root, new_root, before)
    assert switched.root == new_root and switched.retired_root == old_root
    assert switched.cross == _cert(tmp_path, CROSS)
    assert [r.scope for r in switched.rotated] == list(pki.SCOPES)
    assert _mode(tmp_path / CROSS) == 0o644 and _mode(tmp_path / STATE) == 0o644
    # A device that trusts only R reaches a leaf under N through X; one that trusts N
    # stops at N. A leaf of the replaced intermediate still verifies by its retired file.
    inter = _cert(tmp_path, "tunnel.crt")
    leaf = _device_leaf(inter, pki.key_from_pem((tmp_path / "tunnel.key").read_bytes()))
    via_cross = _verify(leaf, [inter, switched.cross], old_root)
    assert via_cross == [leaf, inter, switched.cross, old_root]
    assert _verify(leaf, [inter], new_root) == [leaf, inter, new_root]
    with pytest.raises(VerificationError):
        _verify(leaf, [inter], old_root)
    old_leaf.verify_directly_issued_by(_certs(tmp_path, "tunnel-retired.pem")[0])
    # The issuer still boots on the switched files.
    assert set(storage.ensure_hierarchy(tmp_path, None)) == set(pki.SCOPES)


def test_switch_with_a_compromised_scope_keeps_nothing_of_it(now, tmp_path):
    before, old_root = _staged(tmp_path)
    new_root = _cert(tmp_path, NEXT_CRT)

    rotation.switch_root(tmp_path, NEXT_PW, PW, compromised=frozenset({"access"}))

    _assert_switched(tmp_path, old_root, new_root, before, compromised=("access",))


def test_switch_without_cross_needs_no_root_passphrase(now, tmp_path):
    before, old_root = _staged(tmp_path)
    new_root = _cert(tmp_path, NEXT_CRT)

    switched = rotation.switch_root(tmp_path, NEXT_PW, None, cross=False)

    assert switched.cross is None
    _assert_switched(tmp_path, old_root, new_root, before, cross=False)


@pytest.mark.parametrize(
    ("stage", "kwargs", "match"),
    [
        (
            True,
            {"compromised": frozenset({"access"}), "cross": False},
            "--compromised needs the cross certificate",
        ),
        (False, {}, "cannot switch: no new root is staged"),
        (True, {"next_passphrase": b"wrong"}, r"wrong passphrase .*root-next\.key\.enc"),
        (True, {"root_passphrase": None}, r"needs the passphrase of root\.key\.enc"),
        (True, {"root_passphrase": b"wrong"}, r"wrong passphrase .*root\.key\.enc"),
        (True, {"compromised": frozenset({"acces"})}, "no such scope: acces"),
    ],
)
def test_a_refused_switch_changes_nothing(now, tmp_path, stage, kwargs, match):
    if stage:
        _staged(tmp_path)
    else:
        storage.ensure_hierarchy(tmp_path, PW)
    before = _snapshot(tmp_path)
    args = {"next_passphrase": NEXT_PW, "root_passphrase": PW} | kwargs

    with pytest.raises(rotation.RotationError, match=match):
        rotation.switch_root(tmp_path, **args)

    assert _snapshot(tmp_path) == before


def test_an_expired_old_root_switches_only_without_cross(monkeypatch, tmp_path):
    _at(monkeypatch, pki.VALIDITY_DAYS_ROOT + 1, lambda: storage.ensure_hierarchy(tmp_path, PW))
    old_root = _cert(tmp_path, "root.crt")
    rotation.stage_root(tmp_path, NEXT_PW)
    new_root = _cert(tmp_path, NEXT_CRT)
    staged = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match="not valid now .*--no-cross"):
        rotation.switch_root(tmp_path, NEXT_PW, PW)
    assert _snapshot(tmp_path) == staged

    rotation.switch_root(tmp_path, NEXT_PW, None, cross=False)

    # The expired intermediates under R are replaced but not kept.
    for scope in pki.SCOPES:
        assert _certs(tmp_path, f"{scope}-retired.pem") == []
        assert pki.intermediate_problem(_cert(tmp_path, f"{scope}.crt"), scope, new_root) is None
    assert _cert(tmp_path, RETIRED) == old_root


def test_after_the_switch_only_finish_is_left(now, tmp_path):
    _staged(tmp_path)
    rotation.switch_root(tmp_path, NEXT_PW, PW)
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match="cannot switch: the root switch has run"):
        rotation.switch_root(tmp_path, NEXT_PW, PW)
    with pytest.raises(rotation.RotationError, match="cannot abort: the switch has run"):
        rotation.abort_root(tmp_path)
    with pytest.raises(rotation.RotationError, match="cannot stage: the root switch has run"):
        rotation.stage_root(tmp_path, b"third")

    assert _snapshot(tmp_path) == before


# The writes and removals of a switch, in their order.
SWITCH_STEPS = [
    STATE,
    RETIRED,
    CROSS,
    *(
        f"{scope}{suffix}"
        for scope in pki.SCOPES
        for suffix in ("-retired.pem", ".key", ".crt", "-chain.pem")
    ),
    "root.key.enc",
    "root.crt",
    NEXT_CRT,
    NEXT_KEY,
]


def test_switch_steps_are_the_write_order(monkeypatch, now, tmp_path):
    # The interruption test below walks this list; it holds only if it is the real order.
    _staged(tmp_path)
    seen = []
    real_replace, real_unlink = os.replace, os.unlink

    def replace(src, dst):
        seen.append(os.path.basename(dst))
        real_replace(src, dst)

    def unlink(path, *args, **kwargs):
        if not os.path.basename(path).endswith(".tmp"):
            seen.append(os.path.basename(path))
        real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(os, "replace", replace)
        m.setattr(os, "unlink", unlink)
        rotation.switch_root(tmp_path, NEXT_PW, PW)

    assert seen == SWITCH_STEPS


@pytest.mark.parametrize("target", SWITCH_STEPS)
def test_a_stopped_switch_is_ended_by_the_same_switch(monkeypatch, now, tmp_path, target):
    before, old_root = _staged(tmp_path)
    new_root = _cert(tmp_path, NEXT_CRT)
    with monkeypatch.context() as m:
        _failing(m, target)
        with pytest.raises(rotation.RotationError, match="stopped part way"):
            rotation.switch_root(tmp_path, NEXT_PW, PW)

    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    stopped = _snapshot(tmp_path)
    assert _phase(tmp_path) == ("staged" if target == STATE else "switching")
    if target != STATE:
        # Other options than the stopped run's are refused, and so is everything else.
        with pytest.raises(rotation.RotationError, match="ran with no options"):
            rotation.switch_root(tmp_path, NEXT_PW, PW, compromised=frozenset({"tunnel"}))
        with pytest.raises(rotation.RotationError, match="ran with no options"):
            rotation.switch_root(tmp_path, NEXT_PW, None, cross=False)
        for refused in (
            lambda: rotation.rotate_intermediates(tmp_path, NEXT_PW),
            lambda: rotation.finish_root(tmp_path),
            lambda: rotation.stage_root(tmp_path, NEXT_PW),
        ):
            with pytest.raises(rotation.RotationError, match="switch stopped part way"):
                refused()
        assert _snapshot(tmp_path) == stopped

    # Once X is written R's passphrase is no longer needed.
    has_cross = (tmp_path / CROSS).exists()
    rotation.switch_root(tmp_path, NEXT_PW, None if has_cross else PW)

    _assert_switched(tmp_path, old_root, new_root, before)


# --- finish ------------------------------------------------------------------


def _switched_and_rotated(monkeypatch, tmp_path):
    """Switch 30 days ago, rotate under N today: each retired file then holds the
    intermediate under R and the first one under N. Returns (R, N, first under N)."""
    _, old_root = _at(monkeypatch, 30, lambda: _staged(tmp_path))
    _at(monkeypatch, 30, lambda: rotation.switch_root(tmp_path, NEXT_PW, PW))
    new_root = _cert(tmp_path, "root.crt")
    first = {scope: _cert(tmp_path, f"{scope}.crt") for scope in pki.SCOPES}
    rotation.rotate_intermediates(tmp_path, NEXT_PW)
    return old_root, new_root, first


def test_finish_drops_the_old_root_and_what_is_under_it(monkeypatch, tmp_path):
    old_root, new_root, first = _switched_and_rotated(monkeypatch, tmp_path)
    for scope in pki.SCOPES:
        assert len(_certs(tmp_path, f"{scope}-retired.pem")) == 2

    rotation.finish_root(tmp_path)

    for name in (CROSS, RETIRED, STATE):
        assert not (tmp_path / name).exists(), name
    for scope in pki.SCOPES:
        assert _certs(tmp_path, f"{scope}-retired.pem") == [first[scope]]
    assert _cert(tmp_path, "root.crt") == new_root != old_root
    assert _phase(tmp_path) == "none"
    assert set(storage.ensure_hierarchy(tmp_path, None)) == set(pki.SCOPES)


@pytest.mark.parametrize(("staged", "match"), [(False, "no new root is staged"), (True, "staged")])
def test_finish_before_the_switch_changes_nothing(now, tmp_path, staged, match):
    if staged:
        _staged(tmp_path)
    else:
        storage.ensure_hierarchy(tmp_path, PW)
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=f"cannot finish: .*{match}"):
        rotation.finish_root(tmp_path)

    assert _snapshot(tmp_path) == before


def test_finish_stops_at_a_foreign_retired_entry(now, tmp_path):
    _staged(tmp_path)
    rotation.switch_root(tmp_path, NEXT_PW, PW)
    foreign_root, foreign_key = pki.build_root_ca(label="foreign")
    foreign, _ = pki.build_intermediate_ca("tunnel", foreign_root, foreign_key)
    path = tmp_path / "tunnel-retired.pem"
    path.write_bytes(path.read_bytes() + pki.cert_to_pem(foreign))
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match=r"tunnel-retired\.pem.*then finish again"):
        rotation.finish_root(tmp_path)

    assert _snapshot(tmp_path) == before


FINISH_STEPS = [*(f"{scope}-retired.pem" for scope in pki.SCOPES), CROSS, RETIRED, STATE]


@pytest.mark.parametrize("target", FINISH_STEPS)
def test_a_stopped_finish_is_ended_by_the_same_finish(monkeypatch, tmp_path, target):
    _, new_root, first = _switched_and_rotated(monkeypatch, tmp_path)
    with monkeypatch.context() as m:
        _failing(m, target)
        with pytest.raises(rotation.RotationError, match="stopped part way"):
            rotation.finish_root(tmp_path)

    in_finish = target in (RETIRED, STATE)
    assert _phase(tmp_path) == ("finishing" if in_finish else "switched")
    if in_finish:
        stopped = _snapshot(tmp_path)
        for refused in (
            lambda: rotation.rotate_intermediates(tmp_path, NEXT_PW),
            lambda: rotation.switch_root(tmp_path, NEXT_PW, None),
            lambda: rotation.stage_root(tmp_path, NEXT_PW),
        ):
            with pytest.raises(rotation.RotationError, match="finish stopped part way"):
                refused()
        assert _snapshot(tmp_path) == stopped

    rotation.finish_root(tmp_path)

    assert _phase(tmp_path) == "none"
    for scope in pki.SCOPES:
        assert _certs(tmp_path, f"{scope}-retired.pem") == [first[scope]]
    assert _cert(tmp_path, "root.crt") == new_root


def test_a_second_stage_on_the_day_of_the_first_is_refused(now, tmp_path):
    _staged(tmp_path)
    rotation.switch_root(tmp_path, NEXT_PW, PW)
    rotation.finish_root(tmp_path)
    before = _snapshot(tmp_path)

    with pytest.raises(rotation.RotationError, match="like root.crt; stage on another day"):
        rotation.stage_root(tmp_path, b"third")

    assert _snapshot(tmp_path) == before


# --- the phase as the files show it -------------------------------------------


def _record(**fields) -> bytes:
    record = {
        "switched_at": "2026-11-02T10:00:00+00:00",
        "compromised": [],
        "cross": True,
        "drop_retired_root": False,
    } | fields
    return json.dumps(record).encode()


@pytest.mark.parametrize(
    ("files", "match"),
    [
        ({RETIRED: "root"}, "without root-switch.json"),
        ({CROSS: "root"}, "without root-switch.json"),
        ({NEXT_CRT: "root"}, "has no key root-next.key.enc"),
        ({STATE: b"{"}, "cannot read .*root-switch.json"),
        ({STATE: _record(compromised=["acces"])}, "cannot read .*root-switch.json"),
        ({STATE: _record(switched_at="2026-11-02T10:00:00")}, "cannot read"),
        ({STATE: _record(cross="yes")}, "cannot read"),
        ({STATE: _record(), CROSS: "root"}, "holds root-cross.pem without root-retired.pem"),
        (
            {STATE: _record(cross=False), RETIRED: "root", CROSS: "root"},
            "records a switch without a cross certificate",
        ),
        ({STATE: _record(), RETIRED: b"not a certificate"}, "cannot read .*root-retired.pem"),
    ],
)
def test_files_no_transition_leaves_are_refused(tmp_path, files, match):
    storage.ensure_hierarchy(tmp_path, PW)
    root_pem = (tmp_path / "root.crt").read_bytes()
    for name, data in files.items():
        (tmp_path / name).write_bytes(root_pem if data == "root" else data)
    before = _snapshot(tmp_path)

    with pytest.raises(root_rollover.RolloverError, match=match):
        root_rollover.load_state(tmp_path)
    # A transition reports it as its own error and changes nothing.
    with pytest.raises(rotation.RotationError, match=match):
        rotation.rotate_intermediates(tmp_path, PW)
    assert _snapshot(tmp_path) == before


def test_a_next_key_alone_is_no_stage(tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    (tmp_path / NEXT_KEY).write_bytes(b"left by a stage that stopped")

    assert _phase(tmp_path) == "none"


def test_the_switch_record_round_trips():
    switched_at = datetime.datetime(2026, 11, 2, 10, tzinfo=datetime.UTC)
    record = root_rollover.Switch(switched_at, ("access", "tunnel"), True, True)

    assert root_rollover.Switch.from_json(record.to_json()) == record
    assert root_rollover.Switch.from_json(
        _record(compromised=["tunnel", "access"])
    ).compromised == (
        "access",
        "tunnel",
    )
