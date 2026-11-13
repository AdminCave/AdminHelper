# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The key each host's frpc carries in every proxy (metadatas.ahProxyKey).

frps hands a new proxy's metadatas to the policy plugin in its frps image, which admits
the proxy only if the key belongs to the host the proxy names as its user. The key comes
from SECRET_KEY, the server's ID and its key generation (servers.frp_key_generation), so
the server stores none and every host knows only its own; the plugin's policy file holds
only the SHA-256 of each key. Raising a server's generation replaces its key alone."""

import hashlib
import hmac

from app.core import config

# The metadatas field of a proxy that carries the key; the plugin reads the same name.
PROXY_KEY_META = "ahProxyKey"

# A key of its own for this purpose, so a frpc key never equals a token or other value
# the server derives from SECRET_KEY. The "v1" in the message changes all keys at once.
_KEY_LABEL = b"adminhelper/frp-proxy-key"
_MESSAGE_PREFIX = "frp-proxy-v1:"


def proxy_key(server_id: str, generation: int) -> str:
    """The key of the host with this server ID and key generation, as 64 hex digits."""
    derived = hmac.new(config.SECRET_KEY.encode(), _KEY_LABEL, hashlib.sha256).digest()
    message = _MESSAGE_PREFIX + server_id
    # Generation 0 keeps the message of the keys from before generations existed, so the
    # migration that brought them changed no host's key.
    if generation:
        message += f":{generation}"
    return hmac.new(derived, message.encode(), hashlib.sha256).hexdigest()


def proxy_key_hash(server_id: str, generation: int) -> str:
    """SHA-256 of the key's text, as hex: what the policy file holds for the host."""
    return hashlib.sha256(proxy_key(server_id, generation).encode()).hexdigest()
