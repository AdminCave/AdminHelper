# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identity-header contract gateway <-> server <-> ca-issuer (harness 8a, T2).

The verified mTLS identity travels as two nginx-set headers. Three components
have to agree on their names: the gateway sets them from the client cert, the
server reads them in core/identity.py, the ca-issuer reads them in config.py.
Renaming one side silently turns every mTLS check into "no identity" — a
fail-open in spirit, since the caller then looks like a plain HTTP client.

The certless enrollment plane (:8444) must blank exactly those two, otherwise a
caller without a cert could assert an identity by sending the headers itself.

The ca-issuer constants are read as text, not imported: it is a separate service
with its own venv and is not importable from the server's test run.
"""

import re
from pathlib import Path

from app.core.identity import _H_CERT, _H_VERIFY

_ROOT = Path(__file__).resolve().parents[3]
_GATEWAY = _ROOT / "apps" / "gateway"
_CA_CONFIG = _ROOT / "apps" / "ca-issuer" / "app" / "config.py"

# Only the cert-derived headers are part of the identity contract; the same file
# also forwards Host/X-Forwarded-*, which carry no identity.
_SET_FROM_CERT = re.compile(r"^\s*proxy_set_header\s+(\S+)\s+\$ssl_client_\w+\s*;", re.M)
_BLANKED = re.compile(r'^\s*proxy_set_header\s+(\S+)\s+""\s*;', re.M)
# Only client-identity headers are part of this contract. Without the filter a
# later `proxy_set_header Connection "";` on the enrollment plane (a plausible
# keepalive tweak) would join the set and turn the test red for no drift. The
# filter can only ever produce a false red, never a false green: a rename OUT of
# the namespace still fails, just worded as "not blanked" rather than as a rename.
_IDENTITY_NAME = re.compile(r"^x-client-", re.I)


def _enroll_plane_block() -> str:
    """The `server { … }` block that listens on 8444, by brace matching.

    Scoping matters: a strip found anywhere in the file would also be satisfied
    by one on the :443 data plane, which is the exact opposite of what we want
    there.
    """
    text = (_GATEWAY / "nginx.conf").read_text(encoding="utf-8")
    for match in re.finditer(r"^\s*server\s*\{", text, re.M):
        start = text.index("{", match.start())
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = text[start : i + 1]
        if re.search(r"^\s*listen\s+8444\b", block, re.M):
            return block
    raise AssertionError("no `server` block listening on 8444 found in nginx.conf")


def _server_level(block: str) -> str:
    """`block` minus its nested location blocks — i.e. what a location inherits.

    nginx drops inheritance of the server-level proxy_set_header set as soon as a
    location defines one of its own (identity-headers.conf says so itself). A
    strip that lives only inside one location therefore protects only that
    location; scoping the assertion to the server level is what makes the guard
    mean what its docstring claims.
    """
    out, depth = [], 0
    for ch in block[1:-1]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _cert_headers() -> list[str]:
    conf = (_GATEWAY / "identity-headers.conf").read_text(encoding="utf-8")
    return _SET_FROM_CERT.findall(conf)


def test_gateway_sets_exactly_the_two_identity_headers():
    headers = _cert_headers()
    assert len(headers) == 2, (
        f"identity-headers.conf must set exactly the two cert-derived headers, found: {headers}"
    )


def test_server_and_issuer_read_the_headers_the_gateway_sets():
    gateway = {h.lower() for h in _cert_headers()}

    ca_text = _CA_CONFIG.read_text(encoding="utf-8")
    issuer: dict[str, str] = {}
    for name in ("HEADER_VERIFY", "HEADER_CERT"):
        m = re.search(rf'^{name}\s*=\s*"([^"]+)"', ca_text, re.M)
        assert m, f"{name} not found in {_CA_CONFIG.relative_to(_ROOT)}"
        issuer[name] = m.group(1).lower()

    assert gateway == {_H_VERIFY.lower(), _H_CERT.lower()}, (
        f"server identity headers drifted from the gateway — "
        f"gateway sets {sorted(gateway)}, core/identity.py reads "
        f"{sorted({_H_VERIFY.lower(), _H_CERT.lower()})}"
    )
    assert gateway == set(issuer.values()), (
        f"ca-issuer identity headers drifted from the gateway — "
        f"gateway sets {sorted(gateway)}, ca-issuer config.py reads {sorted(issuer.values())}"
    )


def test_enrollment_plane_blanks_exactly_the_identity_headers():
    blanked = {
        h.lower()
        for h in _BLANKED.findall(_server_level(_enroll_plane_block()))
        if _IDENTITY_NAME.match(h)
    }
    expected = {h.lower() for h in _cert_headers()}
    assert blanked == expected, (
        f"the certless :8444 plane must blank exactly the identity headers at SERVER level — "
        f"not blanked: {sorted(expected - blanked)}, unexpectedly blanked: {sorted(blanked - expected)}"
    )
