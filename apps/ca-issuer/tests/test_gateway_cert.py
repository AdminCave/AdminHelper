# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gateway TLS provisioning (ADR 0001 §3.2): the issuer mints an access-signed
server leaf + trust bundle into a shared volume for the nginx gateway, since the
gateway holds no signing key (D6) and there is no on-device CSR for it."""

import ipaddress

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app import pki
from app.storage import Intermediate, ensure_gateway_cert


def _access_intermediate() -> tuple[Intermediate, x509.Certificate]:
    """Build a Root + access intermediate and wrap it like ensure_hierarchy does."""
    root_cert, root_key = pki.build_root_ca()
    inter_cert, inter_key = pki.build_intermediate_ca("access", root_cert, root_key)
    chain = pki.chain_pem(inter_cert, root_cert)
    return Intermediate(scope="access", cert=inter_cert, key=inter_key, chain=chain), root_cert


# --- build_server_leaf (pki) -------------------------------------------------


def test_build_server_leaf_is_serverauth_with_fresh_key():
    access, _ = _access_intermediate()
    leaf, key = pki.build_server_leaf(access.cert, access.key, "gw.example", ("gw.example",))

    eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert ExtendedKeyUsageOID.CLIENT_AUTH not in eku
    # The issuer generated the key here; the leaf's public key is exactly that key.
    assert leaf.public_key().public_numbers() == key.public_key().public_numbers()
    # Chains to the access intermediate.
    leaf.verify_directly_issued_by(access.cert)
    span = leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert abs(span.days - pki.LEAF_DAYS_GATEWAY) <= 1


# --- ensure_gateway_cert (storage) -------------------------------------------


def test_provisions_three_files_and_chains_to_root(tmp_path):
    access, root_cert = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")

    fullchain = tmp_path / "gateway-fullchain.pem"
    key_path = tmp_path / "gateway.key"
    ca_path = tmp_path / "client-ca.pem"
    assert fullchain.exists() and key_path.exists() and ca_path.exists()

    # fullchain = leaf + access intermediate.
    certs = x509.load_pem_x509_certificates(fullchain.read_bytes())
    leaf, presented_inter = certs[0], certs[1]
    assert presented_inter.subject == access.cert.subject
    leaf.verify_directly_issued_by(access.cert)
    access.cert.verify_directly_issued_by(root_cert)

    # leaf SANs: DOMAIN + the always-added localhost/127.0.0.1.
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("127.0.0.1") in san.get_values_for_type(x509.IPAddress)
    assert leaf.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "localhost"


def test_client_ca_is_the_access_trust_bundle(tmp_path):
    access, root_cert = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")

    # client-ca.pem is exactly the access trust bundle: intermediate + root,
    # which is what nginx ssl_client_certificate needs to verify client certs.
    bundle = (tmp_path / "client-ca.pem").read_bytes()
    assert bundle == access.chain
    parsed = x509.load_pem_x509_certificates(bundle)
    assert [c.subject for c in parsed] == [access.cert.subject, root_cert.subject]


def test_extra_sans_are_classified_into_dns_and_ip(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "admin.example", extra_sans="10.0.0.5, alt.example")

    leaf = x509.load_pem_x509_certificates((tmp_path / "gateway-fullchain.pem").read_bytes())[0]
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "admin.example" in san.get_values_for_type(x509.DNSName)
    assert "alt.example" in san.get_values_for_type(x509.DNSName)
    assert ipaddress.ip_address("10.0.0.5") in san.get_values_for_type(x509.IPAddress)


def test_idempotent_keeps_existing_leaf_key(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    key_before = (tmp_path / "gateway.key").read_bytes()
    cert_before = (tmp_path / "gateway-fullchain.pem").read_bytes()

    ensure_gateway_cert(tmp_path, access, "localhost")  # second boot
    assert (tmp_path / "gateway.key").read_bytes() == key_before
    assert (tmp_path / "gateway-fullchain.pem").read_bytes() == cert_before


def test_gateway_key_is_0600(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    assert (tmp_path / "gateway.key").stat().st_mode & 0o777 == 0o600
