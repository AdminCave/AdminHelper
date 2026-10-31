# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The listed intermediates of each scope for the server (R-1009): current and retired
in ``<scope>.pem``, a compromised one gone after the rotation, never a key."""

import datetime

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from app import main, pki, rotation, storage, trust

PW = b"pw"


def _der(certs) -> list[bytes]:
    return [c.public_bytes(serialization.Encoding.DER) for c in certs]


def _listed(out_dir, scope: str) -> list[x509.Certificate]:
    return x509.load_pem_x509_certificates((out_dir / f"{scope}.pem").read_bytes())


def _rotate(monkeypatch, pki_dir, days_ago: float, compromised=frozenset()):
    then = pki._now() - datetime.timedelta(days=days_ago)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        return rotation.rotate_intermediates(pki_dir, PW, compromised=compromised)


def _boot(monkeypatch, pki_dir, days_ago: float):
    then = pki._now() - datetime.timedelta(days=days_ago)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        return storage.ensure_hierarchy(pki_dir, PW)


def test_writes_current_and_retired_of_every_scope(monkeypatch, tmp_path):
    first = _boot(monkeypatch, tmp_path / "pki", days_ago=10)
    _rotate(monkeypatch, tmp_path / "pki", days_ago=5)
    inter = storage.ensure_hierarchy(tmp_path / "pki", None)

    trust.write_trust(tmp_path / "trust", inter)

    assert sorted(p.name for p in (tmp_path / "trust").iterdir()) == sorted(
        f"{s}.pem" for s in pki.SCOPES
    )
    for scope in pki.SCOPES:
        assert _der(_listed(tmp_path / "trust", scope)) == _der(
            [inter[scope].cert, first[scope].cert]
        )


def test_a_compromised_intermediate_is_not_listed_after_the_rotation(monkeypatch, tmp_path):
    pki_dir = tmp_path / "pki"
    first = _boot(monkeypatch, pki_dir, days_ago=10)
    trust.write_trust(tmp_path / "trust", first)

    _rotate(monkeypatch, pki_dir, days_ago=5, compromised=frozenset({"access"}))
    inter = storage.ensure_hierarchy(pki_dir, None)
    trust.write_trust(tmp_path / "trust", inter)

    assert _der(_listed(tmp_path / "trust", "access")) == _der([inter["access"].cert])
    assert first["access"].cert not in _listed(tmp_path / "trust", "access")
    assert _der(_listed(tmp_path / "trust", "tunnel")) == _der(
        [inter["tunnel"].cert, first["tunnel"].cert]
    )


def test_holds_certificates_only(tmp_path):
    inter = storage.ensure_hierarchy(tmp_path / "pki", PW)
    trust.write_trust(tmp_path / "trust", inter)

    for path in (tmp_path / "trust").iterdir():
        data = path.read_bytes()
        assert b"PRIVATE KEY" not in data
        assert data.count(b"-----BEGIN ") == data.count(b"-----BEGIN CERTIFICATE-----")


def test_boot_writes_the_trust_dir_only_when_configured(monkeypatch, tmp_path):
    inter = storage.ensure_hierarchy(tmp_path / "pki", PW)
    for name in ("CA_GATEWAY_CERT_DIR", "CA_FRPS_CERT_DIR"):
        monkeypatch.setenv(name, "")

    monkeypatch.setenv("CA_TRUST_DIR", "")
    main.provision_boot_material(inter)
    assert not (tmp_path / "trust").exists()

    monkeypatch.setenv("CA_TRUST_DIR", str(tmp_path / "trust"))
    main.provision_boot_material(inter)
    assert _der(_listed(tmp_path / "trust", "internal")) == _der([inter["internal"].cert])
