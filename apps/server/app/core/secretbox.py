# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Encryption of the few secrets the server keeps in its own database (R-1531).

AES-GCM with a key derived by HKDF-SHA256 from SECRET_KEY, so a dump of the database
alone reveals none of them. A sealed value is nonce (12 bytes) followed by ciphertext
and tag; the purpose (the column it lives in) is the associated data, so a value
copied into another column does not open there. After a change of SECRET_KEY nothing
opens any more: unseal() then returns None and the caller falls back to .env."""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core import config

# A key of its own for this purpose: it never equals another value the server derives
# from SECRET_KEY. The "v1" changes all sealed values at once.
_KEY_INFO = b"adminhelper/secretbox-v1"
_NONCE_BYTES = 12


def _aead() -> AESGCM:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_KEY_INFO).derive(
        config.SECRET_KEY.encode()
    )
    return AESGCM(key)


def seal(plain: str, purpose: str) -> bytes:
    """The sealed form of `plain`, bound to `purpose`."""
    nonce = os.urandom(_NONCE_BYTES)
    return nonce + _aead().encrypt(nonce, plain.encode(), purpose.encode())


def unseal(sealed: bytes, purpose: str) -> str | None:
    """The plain text, or None when it does not open with this SECRET_KEY and purpose."""
    if len(sealed) <= _NONCE_BYTES:
        return None
    try:
        plain = _aead().decrypt(sealed[:_NONCE_BYTES], sealed[_NONCE_BYTES:], purpose.encode())
    except InvalidTag:
        return None
    try:
        return plain.decode()
    except UnicodeDecodeError:
        return None
