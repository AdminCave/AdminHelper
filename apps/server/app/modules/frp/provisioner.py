# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Provisioning logic: config hash, activate-endpoint helpers."""

import hashlib

from app.modules.frp.config_generator import generate_frpc_toml


def get_config_hash(
    config, tunnels: list, frpc_user: str, allow_users: list[str] | None = None
) -> str:
    """Computes the SHA256 hash of the generated frpc.toml."""
    toml_content = generate_frpc_toml(config, tunnels, frpc_user, allow_users=allow_users)
    return hashlib.sha256(toml_content.encode()).hexdigest()
