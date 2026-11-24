# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ssl
import time
import zlib
from collections.abc import Callable, Iterator
from typing import NamedTuple

import httpx

from ah_common.ssrf import Target, UrlVerdict, check_target, pinned_client

# Redirects are followed manually (see _fetch) so every hop is re-checked against the
# SSRF guard; cap the chain length like a browser would.
_MAX_REDIRECTS = 5
# As urllib3 (MultiDecoder): each layer holds a decompressor, httpx sets no limit.
_MAX_ENCODINGS = 5
# search_string is looked for in this much of the body and no further: a huge or endless
# response must not fill the scheduler worker's memory (R-0616).
_MAX_BODY_BYTES = 1_048_576
# The deadline's clock; a module name of its own so tests can move it.
_now = time.monotonic


class _Fetched(NamedTuple):
    """What the request hands to the rating: the last response's status code, the part of
    its body read for search_string, the first https hop's certificate and the time taken."""

    status_code: int
    body: str
    truncated: bool
    cert: dict | None
    duration_ms: float


class HttpChecker:
    """HTTP/HTTPS Endpoint Check via httpx."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        expected_status = config.get("expected_status", 200)
        timeout = config.get("timeout", 10)
        # Only a real False turns TLS verification off: a non-bool stored before the
        # strict boundary is the default, as the check editor shows it.
        verify_ssl = config.get("verify_ssl", True) is not False
        search_string = config.get("search_string", "")

        if not url:
            return "unknown", "No URL given", None

        target = check_target(url)
        if target.verdict is UrlVerdict.UNRESOLVED:
            return (
                "unknown",
                "URL host could not be resolved (DNS error or timeout), rejected by the SSRF guard",
                None,
            )
        if target.verdict is not UrlVerdict.ALLOWED:
            return (
                "unknown",
                "URL points to a private/reserved address, rejected by the SSRF guard",
                None,
            )

        try:
            fetched = _fetch(
                url,
                target,
                method=method,
                timeout=timeout,
                verify_ssl=verify_ssl,
                read_body=bool(search_string),
                expected_status=expected_status,
            )
            if isinstance(fetched, str):
                return "critical", fetched, None
            return _rate(fetched, expected_status, search_string, verify_ssl)
        except httpx.TimeoutException:
            return "critical", f"Timeout after {timeout}s", None
        except httpx.ConnectError as exc:
            return "critical", f"Connection failed: {exc}", None
        except Exception as exc:
            return "unknown", f"Error: {exc}", None


def _fetch(
    url: str,
    target: Target,
    *,
    method: str,
    timeout: float,
    verify_ssl: bool,
    read_body: bool,
    expected_status: int,
) -> _Fetched | str:
    """Requests url and follows its redirects, each hop checked by the SSRF guard; with
    read_body the body of a final response with expected_status is read for the rating.
    A str is why the check failed before there was a response to rate (critical)."""
    start = _now()
    # One deadline for the whole check (R-0616): an httpx timeout holds per phase
    # and per request, so it would start over on every redirect hop and every
    # chunk of a body that trickles in. Each request gets what is left of it.
    deadline = start + timeout
    hop_url, hop_target = url, target
    redirects = 0
    body, truncated = "", False
    # The certificate of the first https hop, the one the check's address leads to.
    cert: dict | None = None
    https_seen = False
    while True:
        remaining = deadline - _now()
        if remaining <= 0:
            return f"Timeout after {timeout}s"
        # pinned_client connects to an address check_target checked, not to whatever
        # a second lookup answers. check_target has read the URL with httpx already;
        # the client sits in run's try because building it can fail on an unusable
        # proxy setting from the environment (HTTPS_PROXY=ftp://..., NO_PROXY=host:abc).
        # A client of its own per hop: it connects only to the hop's checked host.
        # stream() reads no body by itself: a redirect's body is never read.
        with (
            pinned_client(hop_url, hop_target, verify=verify_ssl) as client,
            client.stream(method, hop_url, timeout=remaining, follow_redirects=False) as resp,
        ):
            if not https_seen and resp.url.scheme == "https":
                https_seen = True
                # Without verification ssl hands out no fields, only the DER bytes.
                cert = _peer_cert(resp) if verify_ssl else None
            if not resp.is_redirect:
                if read_body and resp.status_code == expected_status:
                    head = _read_head(resp, deadline)
                    if head is None:
                        return f"Timeout after {timeout}s"
                    body, truncated = head
                break
            location = resp.headers.get("location", "")
        # Follow redirects manually and re-check the SSRF guard on every hop.
        # follow_redirects=True would let a public URL 302 into the internal
        # network (VictoriaMetrics, other services, cloud metadata) unchecked.
        # The method is kept across hops (uptime checks are GET and send no
        # body), so no browser-style 303 POST->GET rewrite is needed.
        if not location:
            return "Redirect without Location header"
        if redirects == _MAX_REDIRECTS:
            return f"Too many redirects (>{_MAX_REDIRECTS})"
        next_url = str(resp.url.join(location))
        hop = check_target(next_url)
        if hop.verdict is UrlVerdict.UNRESOLVED:
            return (
                "Redirect target could not be resolved (DNS error or timeout), "
                "rejected by the SSRF guard"
            )
        if hop.verdict is not UrlVerdict.ALLOWED:
            return "Redirect to a private/reserved address, rejected by the SSRF guard"
        hop_url, hop_target = next_url, hop
        redirects += 1
    # Up to what the check rates: the headers, with search_string the part read.
    duration_ms = round((_now() - start) * 1000, 2)
    return _Fetched(resp.status_code, body, truncated, cert, duration_ms)


def _rate(
    fetched: _Fetched, expected_status: int, search_string: str, verify_ssl: bool
) -> tuple[str, str, dict]:
    """The check's result for the response: its status code, then search_string."""
    # A check that reached the endpoint with cert verification off must say so
    # in its result: an "ok" here validated the status code, NOT the TLS cert,
    # so a MITM / expired cert would otherwise pass unnoticed (3.72).
    tls_note = "" if verify_ssl else " [TLS verification disabled]"

    metrics = {
        "http_response_ms": fetched.duration_ms,
        "http_status_code": fetched.status_code,
    }
    if fetched.cert is not None:
        # Popped by the check engine into the state's details; not a metric.
        metrics["_details"] = {"cert": fetched.cert}

    if fetched.status_code != expected_status:
        return (
            "critical",
            f"Status {fetched.status_code} (expected {expected_status}){tls_note}",
            metrics,
        )

    if search_string and search_string not in fetched.body:
        where = "the first 1 MiB of the response" if fetched.truncated else "response"
        return (
            "critical",
            f"Text '{search_string}' not found in {where}{tls_note}",
            metrics,
        )

    return "ok", f"HTTP {fetched.status_code} ({fetched.duration_ms:.0f} ms){tls_note}", metrics


def _peer_cert(resp: httpx.Response) -> dict | None:
    """not_before and not_after (Unix seconds), issuer (CN, else O) and subject_cn of the
    certificate the response's TLS connection verified; None where the transport shows
    no TLS connection. Read while the response is open: the stream closes with it."""
    stream = resp.extensions.get("network_stream")
    ssl_object = stream.get_extra_info("ssl_object") if stream is not None else None
    peer = ssl_object.getpeercert() if ssl_object is not None else None
    if not peer:
        return None
    issuer, subject = _names(peer.get("issuer")), _names(peer.get("subject"))
    return {
        # Always set on a verified certificate, in the "%b %d %H:%M:%S %Y GMT" form
        # cert_time_to_seconds reads; Unix seconds as the agent's tls/certfile probes
        # report not_after.
        "not_before": int(ssl.cert_time_to_seconds(peer["notBefore"])),
        "not_after": int(ssl.cert_time_to_seconds(peer["notAfter"])),
        "issuer": issuer.get("commonName") or issuer.get("organizationName"),
        "subject_cn": subject.get("commonName"),
    }


def _names(rdns) -> dict[str, str]:
    """A getpeercert() name (a tuple of RDNs, each a tuple of (key, value)) as a dict."""
    return {key: value for rdn in rdns or () for key, value in rdn}


def _read_head(resp: httpx.Response, deadline: float) -> tuple[str, bool] | None:
    """The first _MAX_BODY_BYTES of the body as text and whether the body went on;
    None once the deadline passed while reading."""
    data = bytearray()
    for chunk in _decoded(resp, lambda: _MAX_BODY_BYTES + 1 - len(data)):
        data += chunk
        if deadline - _now() <= 0:
            return None
        # One byte past the limit is enough to know the body was cut; a body of exactly
        # the limit is read whole and searched in full.
        if len(data) > _MAX_BODY_BYTES:
            break
    # Decoded as resp.text would: its encoding, undecodable bytes (a character cut at
    # the limit) replaced.
    text = bytes(data[:_MAX_BODY_BYTES]).decode(resp.encoding or "utf-8", errors="replace")
    return text, len(data) > _MAX_BODY_BYTES


def _decoded(resp: httpx.Response, room: Callable[[], int]) -> Iterator[bytes]:
    """The body as resp.iter_bytes() hands it out, but inflated in bounded steps:
    iter_bytes() inflates each raw piece whole, however large that grows. A step of the
    last layer makes at most room() bytes. A step of a layer before it makes at most
    _MAX_BODY_BYTES + 1: its output is input of the next layer, which may have ended
    long before it, and room() falls to 1 once the text is read in full. An empty
    chunk follows every raw piece and every step before the last layer, so the reader
    looks at its deadline also while nothing comes out. room() is at least 1 whenever
    this runs, as the reader stops at its limit; zlib would take 0 for no limit at all."""
    # The decoders httpx 0.28.1 picks (Response._get_content_decoder): the codings in
    # the order they were applied, undone from the last one; identity and a coding it
    # cannot decode (br and zstd lack their packages in the image) leave the bytes as
    # they are.
    codings = [
        coding.strip().lower()
        for coding in resp.headers.get_list("content-encoding", split_commas=True)
    ]
    inflated = [coding for coding in reversed(codings) if coding in ("gzip", "deflate")]
    if len(inflated) > _MAX_ENCODINGS:
        raise httpx.DecodingError(f"Too many content encodings (>{_MAX_ENCODINGS})")
    layers = [_Inflater(coding) for coding in inflated]
    for piece in resp.iter_raw():
        if not layers:
            yield piece
        else:
            layers[0].pending = piece
            # Depth first: what a layer inflates goes through the layers after it before
            # it takes its next step, so no layer holds more than one step's output.
            i = 0
            while i >= 0:
                if not layers[i].busy:
                    i -= 1
                elif i + 1 < len(layers):
                    out = layers[i].step(_MAX_BODY_BYTES + 1)
                    if out:
                        layers[i + 1].pending = out
                        i += 1
                    yield b""
                else:
                    yield layers[i].step(room())
        yield b""


class _Inflater:
    """One gzip or deflate layer of a body, undone as httpx 0.28.1 undoes it
    (httpx/_decoders.py: GZipDecoder, DeflateDecoder), a bounded step at a time."""

    def __init__(self, coding: str) -> None:
        self._zlib = zlib.decompressobj(zlib.MAX_WBITS | 16 if coding == "gzip" else zlib.MAX_WBITS)
        # Deflate is read with the zlib header; if its first piece fails, httpx starts
        # over without the header, and only then.
        self._may_go_raw = coding == "deflate"
        self.pending = b""
        # The last step stopped at its limit: zlib may hold more output.
        self._full = False

    @property
    def busy(self) -> bool:
        # Input after the end of the stream counts for nothing, as in httpx; handed to
        # zlib it would only pile up in unused_data.
        return not self._zlib.eof and (bool(self.pending) or self._full)

    def step(self, limit: int) -> bytes:
        """At most limit bytes inflated from the pending input; the rest stays pending."""
        try:
            out = self._zlib.decompress(self.pending, limit)
        except zlib.error as exc:
            if not self._may_go_raw:
                raise httpx.DecodingError(str(exc)) from exc
            self._zlib = zlib.decompressobj(-zlib.MAX_WBITS)
            self._may_go_raw = False
            return self.step(limit)
        self._may_go_raw = False
        self.pending = self._zlib.unconsumed_tail
        self._full = len(out) == limit
        return out
