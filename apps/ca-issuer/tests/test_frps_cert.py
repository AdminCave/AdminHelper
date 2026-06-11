# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""frps TLS provisioning under the tunnel intermediate (ADR 0001 §3.1 / A7): the
issuer mints the frps server cert + the tunnel trust bundle, replacing frps's
former self-run FRP CA. The CA private key never reaches frps."""

import ipaddress

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

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


def test_ca_is_the_tunnel_trust_bundle(tmp_path):
    tunnel, root_cert = _tunnel_intermediate()
    ensure_frps_cert(tmp_path, tunnel, "frp.example")
    bundle = (tmp_path / "ca.crt").read_bytes()
    assert bundle == tunnel.chain
    parsed = x509.load_pem_x509_certificates(bundle)
    assert [c.subject for c in parsed] == [tunnel.cert.subject, root_cert.subject]


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
