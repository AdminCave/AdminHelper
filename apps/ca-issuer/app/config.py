# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Environment configuration for the ca-issuer.

Boot-time values are read lazily (functions, not import-time constants): reading
os.environ at import froze the paths on first import, so importing app.main
before the env was set up created the PKI under the default dir — an import-order
heisenbug the conftest had to work around. Only ENABLE_DOCS stays eager: it gates
the FastAPI app object built at import time.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Where the PKI material lives (server-only volume; never mounted into frps)."""
    return Path(os.environ.get("CA_DATA_DIR", "/app/data"))


def pki_dir() -> Path:
    return data_dir() / "pki"


def database_url() -> str:
    """Shared AdminHelper DB (read enrollment tokens + revocations). Empty -> the
    in-memory token store is used (tests/dev)."""
    return os.environ.get("DATABASE_URL", "").strip()


def root_passphrase() -> bytes | None:
    """Passphrase that encrypts the cold Root key at rest (D7). Required to create
    the hierarchy on first boot; not needed for normal leaf signing."""
    return os.environ.get("CA_ROOT_PASSPHRASE", "").encode() or None


def gateway_cert_dir() -> str:
    """When set, the issuer provisions the gateway's TLS material here on boot
    (access-signed server leaf + key + trust bundle); the gateway mounts it ro.
    Empty -> no gateway provisioning (tests/dev)."""
    return os.environ.get("CA_GATEWAY_CERT_DIR", "").strip()


def gateway_domain() -> str:
    """CN + primary SAN of the gateway leaf; EXTRA_SANS adds further DNS/IP SANs."""
    return os.environ.get("DOMAIN", "localhost").strip() or "localhost"


def gateway_extra_sans() -> str:
    return os.environ.get("EXTRA_SANS", "").strip()


def frps_cert_dir() -> str:
    """When set, the issuer provisions the frps server cert + tunnel trust bundle
    here on boot (A7); frps mounts it ro. Empty -> no frps provisioning."""
    return os.environ.get("CA_FRPS_CERT_DIR", "").strip()


def frps_server_addr() -> str:
    """CN + primary SAN of the frps leaf = the public frps address frpc connects
    to. Defaults to DOMAIN; set CA_FRPS_SERVER_ADDR if frps is reached under a
    different name/IP than the gateway."""
    return os.environ.get("CA_FRPS_SERVER_ADDR", "").strip() or gateway_domain()


def frps_extra_sans() -> str:
    """Extra SANs for the frps leaf. Own knob (CA_FRPS_EXTRA_SANS) so frps SANs can
    differ from the gateway's; falls back to the gateway SANs when unset — mirroring
    frps_server_addr()'s CA_FRPS_SERVER_ADDR -> gateway_domain() fallback."""
    return os.environ.get("CA_FRPS_EXTRA_SANS", "").strip() or gateway_extra_sans()


# Headers the gateway sets from the verified client cert (ADR 0001 §3.2). The
# issuer trusts these only because the internal listener is reachable solely from
# the gateway (no host port). Contract with apps/gateway/nginx.conf and
# apps/server/app/core/identity.py — change only together with both (the old env
# knobs let the issuer drift from the gateway's hardcoded names and 401 every
# renewal weeks later).
HEADER_VERIFY = "x-client-verify"
HEADER_CERT = "x-client-cert"  # URL-escaped PEM

# Read eagerly: gates the FastAPI app object constructed at import time.
ENABLE_DOCS = os.environ.get("CA_ENABLE_DOCS", "").lower() in ("1", "true", "yes")
