# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The issuer check of a gateway-forwarded client cert (R-1009). nginx anchors client certs
at the root, so a certificate of an intermediate the ca-issuer no longer lists still passes
the gateway; the server accepts one only if a listed intermediate of its scope (current or
retired, CA_TRUST_DIR/<scope>.pem) issued it, and refuses it in both MTLS_ENFORCE modes."""

from __future__ import annotations

import dataclasses
import logging
import os
import urllib.parse

import pytest
from cryptography.hazmat.primitives import serialization

from app.core import config
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT, _is_revoked
from app.core.identity import get_client_identity as identify
from tests import trust_ca
from tests.test_certificate_check import _assert_revoked, _bearer, _me, _record
from tests.test_mtls_scope import _req


def _headers(cert) -> dict[str, str]:
    quoted = urllib.parse.quote(cert.public_bytes(serialization.Encoding.PEM).decode())
    return {"X-Client-Verify": "SUCCESS", "X-Client-Cert": quoted}


def _listed(cert) -> bool:
    return identify(_req(_headers(cert))).issuer_listed


@pytest.fixture
def trust_dir(tmp_path, monkeypatch):
    """A trust directory of the test's own, starting as the ca-issuer writes it."""
    directory = trust_ca.write_trust_dir(tmp_path / "ca-trust")
    monkeypatch.setattr(config, "CA_TRUST_DIR", str(directory))
    return directory


def _rewrite(path, *certs) -> None:
    # A new mtime as the ca-issuer's atomic rename gives, also within one clock tick.
    before = path.stat().st_mtime_ns
    path.write_bytes(trust_ca.pem(*certs))
    os.utime(path, ns=(before + 1_000_000, before + 1_000_000))


def test_a_leaf_of_the_current_intermediate_is_listed():
    assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS)) is True
    assert _listed(trust_ca.leaf("srv-1", SCOPE_AGENT)) is True


def test_a_leaf_of_a_retired_intermediate_is_listed(trust_dir):
    retired = trust_ca.intermediate_of("Retired access intermediate")
    _rewrite(trust_dir / "access.pem", trust_ca.intermediate("access")[0], retired[0])

    assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS, issuer=retired)) is True


def test_a_leaf_of_an_unlisted_intermediate_of_the_same_root_is_refused():
    dropped = trust_ca.intermediate_of("Dropped access intermediate")
    assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS, issuer=dropped)) is False


def test_a_leaf_of_another_scope_s_intermediate_is_refused():
    # The OU names the scope, and only that scope's intermediates count.
    leaf = trust_ca.leaf("srv-1", SCOPE_AGENT, issuer=trust_ca.intermediate("access"))
    assert _listed(leaf) is False


def test_a_self_signed_leaf_and_an_unknown_scope_are_refused():
    assert _listed(trust_ca.leaf("x", "admin")) is False
    assert _listed(trust_ca.leaf("x", None)) is False


def test_a_missing_trust_file_refuses_its_scope_and_logs(trust_dir, caplog):
    (trust_dir / "access.pem").unlink()

    with caplog.at_level(logging.ERROR, logger="adminhelper.identity"):
        assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS)) is False
    assert "access.pem" in caplog.text
    # The other scopes are not affected.
    assert _listed(trust_ca.leaf("srv-1", SCOPE_AGENT)) is True


def test_an_unset_trust_dir_refuses(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CA_TRUST_DIR", str(tmp_path / "never-written"))
    assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS)) is False


def test_a_trust_file_without_certificates_refuses(trust_dir):
    _rewrite(trust_dir / "access.pem")
    assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS)) is False


def test_a_changed_trust_file_is_read_again(trust_dir):
    added = trust_ca.intermediate_of("Added access intermediate")
    leaf = trust_ca.leaf("admin", SCOPE_ACCESS, issuer=added)
    assert _listed(leaf) is False

    _rewrite(trust_dir / "access.pem", trust_ca.intermediate("access")[0], added[0])
    assert _listed(leaf) is True

    _rewrite(trust_dir / "access.pem", trust_ca.intermediate("access")[0])
    assert _listed(leaf) is False


def test_an_identity_counts_only_with_issuer_listed(db_session):
    # A recorded cert the register admits: only issuer_listed decides.
    cert = trust_ca.leaf("admin", SCOPE_ACCESS)
    _record(db_session, cert, "admin")
    identity = identify(_req(_headers(cert)))
    assert identity.issuer_listed is True
    assert _is_revoked(db_session, "admin", SCOPE_ACCESS, identity=identity) is False

    unlisted = dataclasses.replace(identity, issuer_listed=False)
    assert _is_revoked(db_session, "admin", SCOPE_ACCESS, identity=unlisted) is True


def test_an_intermediate_under_the_listed_name_with_another_key_is_refused():
    # The issuer DN is the sender's choice: only the signature tells the listed one apart.
    impostor = trust_ca.intermediate_of("Test access intermediate")
    assert impostor[0].subject == trust_ca.intermediate("access")[0].subject
    assert _listed(trust_ca.leaf("admin", SCOPE_ACCESS, issuer=impostor)) is False


@pytest.mark.parametrize("enforce", [True, False])
def test_a_route_refuses_an_unlisted_issuer_in_both_modes(
    test_client, db_session, admin_user, monkeypatch, enforce
):
    monkeypatch.setattr(config, "MTLS_ENFORCE", enforce)
    dropped = trust_ca.intermediate_of("Dropped access intermediate")
    cert = trust_ca.leaf("admin", SCOPE_ACCESS, issuer=dropped)
    # Recorded in the register as well: only the issuer refuses it.
    _record(db_session, cert, "admin")

    _assert_revoked(_me(test_client, {**_bearer("admin"), **_headers(cert)}))


def test_a_route_admits_a_listed_issuer(test_client, db_session, admin_user, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    cert = trust_ca.leaf("admin", SCOPE_ACCESS)
    _record(db_session, cert, "admin")

    assert _me(test_client, {**_bearer("admin"), **_headers(cert)}).status_code == 200
