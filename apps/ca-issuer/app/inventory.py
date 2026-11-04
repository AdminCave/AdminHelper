# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The snapshot of the infrastructure certificates in the server's database (R-1022).

The server cannot read the PKI volume, so on every start, after the boot material is
provisioned, the ca-issuer writes name, subject, fingerprint and validity of the root,
the roots of a running root renewal (R-1021), the intermediate of each scope and the
gateway's and frps' server certificate (where provisioned) to ``infra_certificates``. A
start is the only time they change: a rotation asks for the restart, and the server
certificates are reissued only at start. All rows are replaced in one transaction, so the
server never sees a half-written snapshot and a certificate that is gone (no frps any more)
leaves no row behind. ``recorded_at`` is the start that first recorded a row's certificate:
for ``root`` the first start under it, from which on the ca-issuer signs under it.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from sqlalchemy import Engine, delete, select

from app import pki, root_rollover
from app.db import infra_certificates


def _naive_utc(at: datetime.datetime) -> datetime.datetime:
    return at.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def collect(
    pki_dir: Path, gateway_dir: Path | None, frps_dir: Path | None
) -> dict[str, x509.Certificate]:
    """Name -> certificate. Root and intermediates must be readable (the hierarchy was
    loaded before); a server certificate counts only where its directory is configured and
    its file is there. The first certificate of a fullchain is its leaf. A root renewal adds
    root:next (staged), root:retired and root:cross (switched, the cross certificate not
    after --no-cross); root stays root.crt, the root that signs."""
    certs = {"root": pki.cert_from_pem((pki_dir / "root.crt").read_bytes())}
    renewal = root_rollover.load_state(pki_dir)
    for name, cert in (
        ("root:next", renewal.next_root),
        ("root:retired", renewal.retired_root),
        ("root:cross", renewal.cross),
    ):
        if cert is not None:
            certs[name] = cert
    for scope in pki.SCOPES:
        certs[f"intermediate:{scope}"] = pki.cert_from_pem((pki_dir / f"{scope}.crt").read_bytes())
    for name, path in (
        ("gateway", gateway_dir and gateway_dir / "gateway-fullchain.pem"),
        ("frps", frps_dir and frps_dir / "frps.crt"),
    ):
        if path and path.is_file():
            certs[name] = x509.load_pem_x509_certificate(path.read_bytes())
    return certs


def record(engine: Engine, certs: dict[str, x509.Certificate]) -> None:
    now = _naive_utc(pki._now())  # the clock the leaves get their not_before from
    with engine.begin() as conn:
        c = infra_certificates.c
        # rotate-root finish counts a device as renewed under the root from the first start
        # under it on: until that restart the old process still signs under the old root.
        first = {
            (row.name, row.fingerprint): row.recorded_at
            for row in conn.execute(select(c.name, c.fingerprint, c.recorded_at))
        }
        rows = []
        for name, cert in certs.items():
            fingerprint = cert.fingerprint(hashes.SHA256()).hex()
            rows.append(
                {
                    "name": name,
                    "subject": cert.subject.rfc4514_string(),
                    "fingerprint": fingerprint,
                    "not_before": _naive_utc(cert.not_valid_before_utc),
                    "not_after": _naive_utc(cert.not_valid_after_utc),
                    "recorded_at": first.get((name, fingerprint), now),
                }
            )
        conn.execute(delete(infra_certificates))
        conn.execute(infra_certificates.insert(), rows)
