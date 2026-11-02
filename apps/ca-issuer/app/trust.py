# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The listed intermediates of each scope for the server (R-1009).

The gateway (nginx) can anchor client certificates only at the self-signed root, so it
lets through a certificate of any intermediate under that root that the client sends
along, also of one that ``rotate-intermediates --compromised`` dropped. The server
therefore checks the issuer itself, against what this module writes on every start:
one ``<scope>.pem`` per scope in CA_TRUST_DIR with the current and the retired
intermediates of that scope, certificates only. A dropped intermediate is in neither, so
after the restart the rotation asks for, the server refuses its certificates.
"""

from __future__ import annotations

from pathlib import Path

from app import pki
from app.storage import Intermediate, _write_atomic


def write_trust(out_dir: Path, intermediates: dict[str, Intermediate]) -> None:
    """Write ``<scope>.pem`` (current + retired intermediates) for every scope, each file
    replaced atomically so the server never reads half a bundle."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for scope in pki.SCOPES:
        inter = intermediates[scope]
        _write_atomic(out_dir / f"{scope}.pem", pki.chain_pem(inter.cert, *inter.retired))
