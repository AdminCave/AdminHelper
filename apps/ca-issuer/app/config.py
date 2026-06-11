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

# When set, the issuer provisions the gateway's TLS material here on boot
# (access-signed server leaf + key + the access trust bundle); the gateway mounts
# this dir read-only. Empty -> no gateway provisioning (tests/dev).
GATEWAY_CERT_DIR = os.environ.get("CA_GATEWAY_CERT_DIR", "").strip()
# CN + primary SAN of the gateway leaf; EXTRA_SANS adds further DNS/IP SANs.
GATEWAY_DOMAIN = os.environ.get("DOMAIN", "localhost").strip() or "localhost"
GATEWAY_EXTRA_SANS = os.environ.get("EXTRA_SANS", "").strip()

# When set, the issuer provisions the frps server cert + tunnel trust bundle here
# on boot (A7); frps mounts this dir read-only. Empty -> no frps provisioning.
FRPS_CERT_DIR = os.environ.get("CA_FRPS_CERT_DIR", "").strip()
# CN + primary SAN of the frps leaf = the public frps address frpc connects to.
# Defaults to DOMAIN; set CA_FRPS_SERVER_ADDR if frps is reached under a different
# name/IP than the gateway.
FRPS_SERVER_ADDR = os.environ.get("CA_FRPS_SERVER_ADDR", "").strip() or GATEWAY_DOMAIN
FRPS_EXTRA_SANS = os.environ.get("EXTRA_SANS", "").strip()

# Header the gateway sets from the verified client cert (ADR 0001 §3.2). The
# issuer trusts these only because the internal listener is reachable solely
# from the gateway (no host port).
HEADER_VERIFY = os.environ.get("CA_HEADER_VERIFY", "x-client-verify")
HEADER_CERT = os.environ.get("CA_HEADER_CERT", "x-client-cert")  # URL-escaped PEM

# Interactive docs stay off unless explicitly enabled (internal-only service).
ENABLE_DOCS = os.environ.get("CA_ENABLE_DOCS", "").lower() in ("1", "true", "yes")
