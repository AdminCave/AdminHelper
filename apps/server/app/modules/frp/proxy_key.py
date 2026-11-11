# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The key each host's frpc carries in every proxy (metadatas.ahProxyKey).

frps hands a new proxy's metadatas to the policy plugin in its frps image, which admits
the proxy only if the key belongs to the host the proxy names as its user. The key comes
from SECRET_KEY and the server's ID, so the server stores none and every host knows only
its own; the plugin's policy file holds only the SHA-256 of each key."""

import hashlib
import hmac

from app.core import config

# The metadatas field of a proxy that carries the key; the plugin reads the same name.
PROXY_KEY_META = "ahProxyKey"

# A key of its own for this purpose, so a frpc key never equals a token or other value
# the server derives from SECRET_KEY. The "v1" in the message changes all keys at once.
_KEY_LABEL = b"adminhelper/frp-proxy-key"
_MESSAGE_PREFIX = "frp-proxy-v1:"


def proxy_key(server_id: str) -> str:
    """The key of the host with this server ID, as 64 hex digits."""
    derived = hmac.new(config.SECRET_KEY.encode(), _KEY_LABEL, hashlib.sha256).digest()
    return hmac.new(derived, (_MESSAGE_PREFIX + server_id).encode(), hashlib.sha256).hexdigest()


def proxy_key_hash(server_id: str) -> str:
    """SHA-256 of the key's text, as hex: what the policy file holds for the host."""
    return hashlib.sha256(proxy_key(server_id).encode()).hexdigest()
