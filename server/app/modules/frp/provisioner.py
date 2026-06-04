# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Provisioning logic: config hash, activate-endpoint helpers."""

import base64
import hashlib
import io
import tarfile
from typing import Optional

from app.modules.frp.config_generator import generate_frpc_toml
from app.modules.frp import pki as pki_manager


def get_config_hash(config, tunnels: list, frpc_user: str, allow_users: list[str] | None = None) -> str:
    """Computes the SHA256 hash of the generated frpc.toml."""
    toml_content = generate_frpc_toml(config, tunnels, frpc_user, allow_users=allow_users)
    return hashlib.sha256(toml_content.encode()).hexdigest()


def build_pki_bundle_b64(client_name: str) -> Optional[str]:
    """Creates a base64-encoded tar.gz with PKI files for a client."""
    d = pki_manager.PKI_DIR
    ca_crt = d / "ca.crt"
    client_crt = d / f"{client_name}.crt"
    client_key = d / f"{client_name}.key"

    # Check that all files exist
    if not ca_crt.exists():
        return None
    if not client_crt.exists() or not client_key.exists():
        return None

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(ca_crt), arcname="pki/ca.crt")
        tar.add(str(client_crt), arcname=f"pki/{client_name}.crt")
        tar.add(str(client_key), arcname=f"pki/{client_name}.key")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()
