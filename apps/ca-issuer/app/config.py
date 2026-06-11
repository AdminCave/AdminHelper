# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Environment configuration for the ca-issuer."""

from __future__ import annotations

import os
from pathlib import Path

# Where the PKI material lives (server-only volume; never mounted into frps).
DATA_DIR = Path(os.environ.get("CA_DATA_DIR", "/app/data"))
PKI_DIR = DATA_DIR / "pki"

# Shared AdminHelper DB (read enrollment tokens + revocations). Empty -> the
# in-memory token store is used (tests/dev).
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Passphrase that encrypts the cold Root key at rest (D7). Required to create
# the hierarchy on first boot; not needed for normal leaf signing (the root is
# never touched once the intermediates exist).
ROOT_PASSPHRASE = os.environ.get("CA_ROOT_PASSPHRASE", "").encode() or None

# Header the gateway sets from the verified client cert (ADR 0001 §3.2). The
# issuer trusts these only because the internal listener is reachable solely
# from the gateway (no host port).
HEADER_VERIFY = os.environ.get("CA_HEADER_VERIFY", "x-client-verify")
HEADER_CERT = os.environ.get("CA_HEADER_CERT", "x-client-cert")  # URL-escaped PEM

# Interactive docs stay off unless explicitly enabled (internal-only service).
ENABLE_DOCS = os.environ.get("CA_ENABLE_DOCS", "").lower() in ("1", "true", "yes")
