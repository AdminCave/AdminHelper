# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The renew proof as the issuer checks it, on a fixed vector that the agent
(internal/enroll/renew_test.go) and the desktop (enrollment.rs) check too, each with its own copy
of the prefix: a copy that drifts turns its own test red instead of every renew into a 403
(R-1812)."""

import json
from pathlib import Path

import pytest
from cryptography import x509

from app import issuer
from app.issuer import IssuanceError

_VECTOR = json.loads(
    (Path(__file__).parent / "fixtures" / "renew_proof_vector.json").read_text(encoding="utf-8")
)


def test_the_issuer_accepts_the_shared_vector():
    cert = x509.load_pem_x509_certificate(_VECTOR["cert"].encode())
    csr = x509.load_pem_x509_csr(_VECTOR["csr"].encode())
    issuer._check_proof(cert, csr, _VECTOR["proof"])


def test_the_shared_vector_is_bound_to_the_prefix(monkeypatch):
    cert = x509.load_pem_x509_certificate(_VECTOR["cert"].encode())
    csr = x509.load_pem_x509_csr(_VECTOR["csr"].encode())
    monkeypatch.setattr(issuer, "RENEW_PROOF_PREFIX", b"AdminHelper renew v2\x00")
    with pytest.raises(IssuanceError):
        issuer._check_proof(cert, csr, _VECTOR["proof"])
