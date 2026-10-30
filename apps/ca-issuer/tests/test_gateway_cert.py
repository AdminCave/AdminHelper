# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gateway TLS provisioning (ADR 0001 §3.2): the issuer mints an access-signed
server leaf + trust bundle into a shared volume for the nginx gateway, since the
gateway holds no signing key (D6) and there is no on-device CSR for it."""

import ipaddress

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
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

    # fullchain = leaf + access intermediate (+ root, see the R-0667 tests below).
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


def _names(path) -> tuple[set[str], set]:
    leaf = x509.load_pem_x509_certificates(path.read_bytes())[0]
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return set(san.get_values_for_type(x509.DNSName)), set(san.get_values_for_type(x509.IPAddress))


def test_remints_when_extra_sans_change(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "admin.example", extra_sans="alt.example")
    key_before = (tmp_path / "gateway.key").read_bytes()

    ensure_gateway_cert(tmp_path, access, "admin.example", extra_sans="alt.example, 192.0.2.10")

    dns, ips = _names(tmp_path / "gateway-fullchain.pem")
    assert ipaddress.ip_address("192.0.2.10") in ips
    assert "alt.example" in dns
    assert (tmp_path / "gateway.key").read_bytes() != key_before


def test_remints_when_the_domain_changes(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "old.example")

    ensure_gateway_cert(tmp_path, access, "new.example")

    dns, _ = _names(tmp_path / "gateway-fullchain.pem")
    assert "new.example" in dns and "old.example" not in dns


def test_keeps_the_leaf_when_extra_sans_only_change_order_or_spacing(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "admin.example", extra_sans="alt.example,192.0.2.10")
    cert_before = (tmp_path / "gateway-fullchain.pem").read_bytes()

    ensure_gateway_cert(tmp_path, access, "admin.example", extra_sans=" 192.0.2.10 , alt.example ")

    assert (tmp_path / "gateway-fullchain.pem").read_bytes() == cert_before


def test_gateway_key_is_0600(tmp_path):
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    assert (tmp_path / "gateway.key").stat().st_mode & 0o777 == 0o600


# --- F4: re-mint the leaf before it expires ----------------------------------


def test_leaf_needs_remint_detects_missing_and_fresh(tmp_path):
    from app.storage import _leaf_needs_remint

    assert _leaf_needs_remint(tmp_path / "nope.pem") is True  # missing -> re-mint

    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    assert _leaf_needs_remint(tmp_path / "gateway-fullchain.pem") is False  # fresh -> keep


def test_remints_leaf_once_past_half_life(tmp_path, monkeypatch):
    import datetime

    # First boot: mint a leaf dated ~300 days ago (well past half of its 365-day
    # life) by pinning the issuer clock to the past for this call only. The leaf
    # has no client-side auto-renew, so without F4 it would simply expire and take
    # the gateway down with it. The hierarchy is minted on the same past clock: an
    # intermediate younger than the leaf would be not yet valid and refuse to sign.
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=300)
    monkeypatch.setattr(pki, "_now", lambda: past)
    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    aged = (tmp_path / "gateway-fullchain.pem").read_bytes()
    monkeypatch.undo()  # back to the real clock

    # Second boot (real clock): the aged leaf is re-minted before it can expire.
    ensure_gateway_cert(tmp_path, access, "localhost")
    fresh = (tmp_path / "gateway-fullchain.pem").read_bytes()
    assert fresh != aged
    leaf = x509.load_pem_x509_certificates(fresh)[0]
    assert leaf.not_valid_before_utc > past + datetime.timedelta(days=200)


def test_gateway_cert_remints_on_key_leaf_mismatch(tmp_path):
    # 4.19: a crash between writing the leaf and the key leaves a NEW leaf beside an OLD key.
    # The guard must detect the mismatch and re-mint, not skip because the leaf is 0% aged.
    from app.storage import _pair_matches

    access, _ = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    fullchain = tmp_path / "gateway-fullchain.pem"
    key_path = tmp_path / "gateway.key"
    # Simulate the half-written pair: replace the key with a different freshly-minted one.
    stale = pki.key_to_pem(pki.generate_key())
    key_path.write_bytes(stale)
    assert not _pair_matches(fullchain, key_path)  # mismatch detected
    ensure_gateway_cert(tmp_path, access, "localhost")  # re-run
    assert _pair_matches(fullchain, key_path)  # re-minted to a matching pair
    assert key_path.read_bytes() != stale


def test_ensure_hierarchy_aborts_on_partial_pki(tmp_path):
    # 4.18: a crash mid-first-boot leaves the root but a missing intermediate; the next boot
    # must abort with a clear error, not skip creation and FileNotFoundError in the load loop.
    from app.storage import ensure_hierarchy

    ensure_hierarchy(tmp_path, root_passphrase=b"pw")  # full first boot
    (tmp_path / f"{pki.SCOPES[0]}.key").unlink()  # simulate a partial dir
    with pytest.raises(RuntimeError, match="unvollständig"):
        ensure_hierarchy(tmp_path, root_passphrase=b"pw")


# --- R-0667: after a rotation (retired access intermediates) ------------------


def _rotated_access() -> tuple[Intermediate, Intermediate, x509.Certificate]:
    """Two access intermediates under one root, as after a rotation: the retired
    one (with its key, to mint leaves under it) and the current one, which lists
    the retired one like ensure_hierarchy does."""
    root_cert, root_key = pki.build_root_ca()
    old_cert, old_key = pki.build_intermediate_ca("access", root_cert, root_key)
    new_cert, new_key = pki.build_intermediate_ca("access", root_cert, root_key)
    old = Intermediate("access", old_cert, old_key, pki.chain_pem(old_cert, root_cert))
    chain = pki.chain_pem(new_cert, root_cert)
    current = Intermediate("access", new_cert, new_key, chain, retired=(old_cert,))
    return old, current, root_cert


def _der(certs) -> list[bytes]:
    return [c.public_bytes(serialization.Encoding.DER) for c in certs]


def _signed_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    try:
        cert.verify_directly_issued_by(issuer)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def test_client_ca_carries_the_retired_access_intermediates(tmp_path):
    old, access, root_cert = _rotated_access()
    ensure_gateway_cert(tmp_path, access, "localhost")

    bundle = x509.load_pem_x509_certificates((tmp_path / "client-ca.pem").read_bytes())
    assert _der(bundle) == _der([access.cert, root_cert, old.cert])
    # A cert from before the rotation sent without its chain (like a browser .p12):
    # nginx finds its issuer only because the retired intermediate is in the bundle.
    leaf, _ = pki.build_server_leaf(old.cert, old.key, "before-rotation")
    assert _der(c for c in bundle if _signed_by(leaf, c)) == _der([old.cert])


def test_remints_a_leaf_of_a_retired_intermediate_under_the_current(tmp_path):
    old, access, _ = _rotated_access()
    ensure_gateway_cert(tmp_path, old, "localhost")  # last boot before the rotation
    key_before = (tmp_path / "gateway.key").read_bytes()

    ensure_gateway_cert(tmp_path, access, "localhost")  # first boot after it
    certs = x509.load_pem_x509_certificates((tmp_path / "gateway-fullchain.pem").read_bytes())
    certs[0].verify_directly_issued_by(access.cert)
    assert _der(certs[1:2]) == _der([access.cert])
    assert (tmp_path / "gateway.key").read_bytes() != key_before


def test_keeps_a_fresh_leaf_of_the_current_intermediate_beside_retired_ones(tmp_path):
    _, access, _ = _rotated_access()
    ensure_gateway_cert(tmp_path, access, "localhost")
    key_before = (tmp_path / "gateway.key").read_bytes()
    cert_before = (tmp_path / "gateway-fullchain.pem").read_bytes()

    ensure_gateway_cert(tmp_path, access, "localhost")  # second boot
    assert (tmp_path / "gateway.key").read_bytes() == key_before
    assert (tmp_path / "gateway-fullchain.pem").read_bytes() == cert_before


# --- R-0667: the gateway sends the root, so --ca-fp can pin it ----------------


def test_fullchain_ends_with_the_root_of_the_hierarchy(tmp_path):
    from app.storage import ensure_hierarchy

    pki_dir, out = tmp_path / "pki", tmp_path / "gateway"
    access = ensure_hierarchy(pki_dir, root_passphrase=b"pw")["access"]
    ensure_gateway_cert(out, access, "localhost")

    certs = x509.load_pem_x509_certificates((out / "gateway-fullchain.pem").read_bytes())
    root_cert = x509.load_pem_x509_certificate((pki_dir / "root.crt").read_bytes())
    assert len(certs) == 3
    assert _der(certs[1:]) == _der([access.cert, root_cert])
    certs[0].verify_directly_issued_by(access.cert)


def test_remints_a_fresh_fullchain_without_the_root(tmp_path):
    access, root_cert = _access_intermediate()
    ensure_gateway_cert(tmp_path, access, "localhost")
    fullchain = tmp_path / "gateway-fullchain.pem"
    key_path = tmp_path / "gateway.key"
    # A fresh leaf of the current intermediate, written as before the root went along.
    leaf, inter = x509.load_pem_x509_certificates(fullchain.read_bytes())[:2]
    fullchain.write_bytes(pki.cert_to_pem(leaf) + pki.cert_to_pem(inter))
    key_before = key_path.read_bytes()

    ensure_gateway_cert(tmp_path, access, "localhost")  # next boot
    certs = x509.load_pem_x509_certificates(fullchain.read_bytes())
    assert _der(certs[1:]) == _der([access.cert, root_cert])
    certs[0].verify_directly_issued_by(access.cert)
    assert key_path.read_bytes() != key_before
