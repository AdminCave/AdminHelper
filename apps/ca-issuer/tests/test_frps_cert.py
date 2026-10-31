# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""frps TLS provisioning under the tunnel intermediate (ADR 0001 §3.1 / A7): the
issuer mints the frps server cert + the tunnel trust bundle, replacing frps's
former self-run FRP CA. The CA private key never reaches frps."""

import datetime
import ipaddress

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from app import pki
from app.storage import Intermediate, ensure_frps_cert


def _tunnel_intermediate() -> tuple[Intermediate, x509.Certificate]:
    root_cert, root_key = pki.build_root_ca()
    inter_cert, inter_key = pki.build_intermediate_ca("tunnel", root_cert, root_key)
    chain = pki.chain_pem(inter_cert, root_cert)
    return Intermediate(scope="tunnel", cert=inter_cert, key=inter_key, chain=chain), root_cert


def test_provisions_serverauth_leaf_under_tunnel(tmp_path):
    tunnel, root_cert = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example", extra_sans="203.0.113.7")

    cert_path = tmp_path / "frps.crt"
    key_path = tmp_path / "frps.key"
    ca_path = tmp_path / "ca.crt"
    assert cert_path.exists() and key_path.exists() and ca_path.exists()

    # frps.crt = leaf + tunnel intermediate; leaf chains tunnel -> root.
    certs = x509.load_pem_x509_certificates(cert_path.read_bytes())
    assert len(certs) == 2  # no root: only the gateway sends it along (R-0667)
    leaf, presented_inter = certs[0], certs[1]
    assert presented_inter.subject == tunnel.cert.subject
    leaf.verify_directly_issued_by(tunnel.cert)
    tunnel.cert.verify_directly_issued_by(root_cert)

    # server_auth, CN = server_addr, SANs incl. the extra IP + always localhost.
    eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert leaf.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "frp.example"
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "frp.example" in san.get_values_for_type(x509.DNSName)
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("203.0.113.7") in san.get_values_for_type(x509.IPAddress)


def test_ca_is_the_tunnel_trust_bundle_without_the_root(tmp_path):
    tunnel, _root_cert = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    bundle = (tmp_path / "ca.crt").read_bytes()
    assert bundle == pki.cert_to_pem(tunnel.cert)
    parsed = x509.load_pem_x509_certificates(bundle)
    # R-1009: no self-signed certificate, so the root is no anchor for frps.
    assert all(c.subject != c.issuer for c in parsed)


def test_ca_trusts_access_visitor_certs_with_extra_trust(tmp_path):
    # F2: the desktop STCP visitor presents its ACCESS cert, so frps must trust
    # the access intermediate alongside tunnel — without re-signing its own leaf.
    root_cert, root_key = pki.build_root_ca()
    tunnel_cert, tunnel_key = pki.build_intermediate_ca("tunnel", root_cert, root_key)
    access_cert, access_key = pki.build_intermediate_ca("access", root_cert, root_key)
    tunnel = Intermediate("tunnel", tunnel_cert, tunnel_key, pki.chain_pem(tunnel_cert, root_cert))
    access = Intermediate("access", access_cert, access_key, pki.chain_pem(access_cert, root_cert))

    ensure_frps_cert(tmp_path, tunnel, "frp.example", extra_trust=(access,))

    subjects = [
        c.subject for c in x509.load_pem_x509_certificates((tmp_path / "ca.crt").read_bytes())
    ]
    assert tunnel_cert.subject in subjects
    assert root_cert.subject not in subjects
    assert access_cert.subject in subjects  # the visitor's trust anchor

    # frps presents a tunnel-signed leaf (unchanged), not access.
    frps_leaf = x509.load_pem_x509_certificates((tmp_path / "frps.crt").read_bytes())[0]
    frps_leaf.verify_directly_issued_by(tunnel_cert)
    # An access-signed visitor leaf chains to an intermediate present in the bundle.
    visitor_leaf, _ = pki.build_server_leaf(access_cert, access_key, "desktop-visitor")
    visitor_leaf.verify_directly_issued_by(access_cert)


def test_remints_when_the_frps_extra_sans_change(tmp_path):
    tunnel, _ = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")

    ensure_frps_cert(tmp_path, tunnel, "frp.example", extra_sans="203.0.113.7")

    leaf = x509.load_pem_x509_certificates((tmp_path / "frps.crt").read_bytes())[0]
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("203.0.113.7") in san.get_values_for_type(x509.IPAddress)


def test_idempotent_keeps_existing_frps_key(tmp_path):
    tunnel, _ = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    key_before = (tmp_path / "frps.key").read_bytes()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    assert (tmp_path / "frps.key").read_bytes() == key_before


def test_frps_key_is_0600(tmp_path):
    tunnel, _ = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    assert (tmp_path / "frps.key").stat().st_mode & 0o777 == 0o600


def test_remints_frps_leaf_once_past_half_life(tmp_path, monkeypatch):
    import datetime

    # First boot: mint an frps leaf dated ~300 days ago (past half of its life),
    # under a hierarchy minted on the same past clock (an intermediate younger
    # than the leaf would be not yet valid and refuse to sign).
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300)
    monkeypatch.setattr(pki, "_now", lambda: past)
    tunnel, _ = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    aged = (tmp_path / "frps.crt").read_bytes()
    monkeypatch.undo()

    # Second boot (real clock): the aged frps leaf is re-minted before it expires
    # and breaks the tunnel edge (F4).
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    assert (tmp_path / "frps.crt").read_bytes() != aged


# --- R-0667: after a rotation (retired intermediates) ------------------------


def _generations(scope: str, root_cert, root_key) -> tuple[Intermediate, Intermediate]:
    """Two intermediates of `scope` under the root, as after a rotation: the retired
    one (with its key, to mint leaves under it) and the current one, which lists
    the retired one like ensure_hierarchy does."""
    old_cert, old_key = pki.build_intermediate_ca(scope, root_cert, root_key)
    new_cert, new_key = pki.build_intermediate_ca(scope, root_cert, root_key)
    old = Intermediate(scope, old_cert, old_key, pki.chain_pem(old_cert, root_cert))
    chain = pki.chain_pem(new_cert, root_cert)
    return old, Intermediate(scope, new_cert, new_key, chain, retired=(old_cert,))


def _der(certs) -> list[bytes]:
    return [c.public_bytes(serialization.Encoding.DER) for c in certs]


def _signed_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    try:
        cert.verify_directly_issued_by(issuer)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def test_ca_carries_current_and_retired_of_tunnel_and_extra_trust(tmp_path):
    root_cert, root_key = pki.build_root_ca()
    old_tunnel, tunnel = _generations("tunnel", root_cert, root_key)
    old_access, access = _generations("access", root_cert, root_key)

    ensure_frps_cert(tmp_path, tunnel, "frp.example", extra_trust=(access,))

    bundle = x509.load_pem_x509_certificates((tmp_path / "ca.crt").read_bytes())
    assert _der(bundle) == _der([tunnel.cert, old_tunnel.cert, access.cert, old_access.cert])
    # An agent (tunnel) and a visitor (access) cert from before the rotation, sent
    # without their chain, each find their issuer in the bundle.
    for old in (old_tunnel, old_access):
        leaf, _ = pki.build_server_leaf(old.cert, old.key, "before-rotation")
        assert _der(c for c in bundle if _signed_by(leaf, c)) == _der([old.cert])


def test_remints_an_frps_leaf_of_a_retired_tunnel_intermediate(tmp_path):
    root_cert, root_key = pki.build_root_ca()
    old, tunnel = _generations("tunnel", root_cert, root_key)
    ensure_frps_cert(tmp_path, old, "frp.example")  # last boot before the rotation
    key_before = (tmp_path / "frps.key").read_bytes()

    ensure_frps_cert(tmp_path, tunnel, "frp.example")  # first boot after it
    certs = x509.load_pem_x509_certificates((tmp_path / "frps.crt").read_bytes())
    certs[0].verify_directly_issued_by(tunnel.cert)
    assert _der(certs[1:2]) == _der([tunnel.cert])
    assert (tmp_path / "frps.key").read_bytes() != key_before


def _client_leaf(issuer: x509.Certificate, issuer_key, scope: str) -> x509.Certificate:
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "device")]))
        .sign(key, hashes.SHA256())
    )
    # The SAN only satisfies the client-verifier profile of cryptography; the anchor
    # logic under test does not depend on it.
    spec = pki.LeafSpec(
        lifetime_days=pki.LEAF_DAYS_NATIVE,
        client_auth=True,
        server_auth=False,
        subject_cn="device",
        scope=scope,
        dns_names=("device",),
    )
    return pki.sign_leaf(csr, issuer, issuer_key, spec)


def _verifier(bundle_path):
    # Like Go's crypto/tls in frps: every certificate in the pool is an anchor.
    store = Store(x509.load_pem_x509_certificates(bundle_path.read_bytes()))
    now = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=1)
    return PolicyBuilder().store(store).time(now).build_client_verifier()


def test_ca_accepts_only_what_a_listed_intermediate_issued(tmp_path):
    # R-1009: an intermediate dropped from the bundle (rotate --compromised) shares the
    # root with the listed ones; a client sending it along must still be refused.
    root_cert, root_key = pki.build_root_ca()
    old_tunnel, tunnel = _generations("tunnel", root_cert, root_key)
    _old_access, access = _generations("access", root_cert, root_key)
    dropped_cert, dropped_key = pki.build_intermediate_ca("tunnel", root_cert, root_key)

    ensure_frps_cert(tmp_path, tunnel, "frp.example", extra_trust=(access,))
    verifier = _verifier(tmp_path / "ca.crt")

    for issuer, key in ((tunnel.cert, tunnel.key), (old_tunnel.cert, old_tunnel.key)):
        leaf = _client_leaf(issuer, key, "tunnel")
        chain = verifier.verify(leaf, [issuer, root_cert]).chain
        assert _der(chain) == _der([leaf, issuer])
    verifier.verify(_client_leaf(access.cert, access.key, "access"), [access.cert])

    foreign = _client_leaf(dropped_cert, dropped_key, "tunnel")
    with pytest.raises(VerificationError):
        verifier.verify(foreign, [dropped_cert, root_cert])
