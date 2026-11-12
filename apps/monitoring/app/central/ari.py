# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ACME Renewal Information (RFC 9773) for the sensor tls (R-1224).

The CA that issued a certificate says by an unauthenticated GET when it suggests
renewing it. A window wholly in the past is its call to renew at once (RFC 9773
§6), as before a mass revocation; a window that has ended while the certificate is
still served is renewal overdue by the CA's own word. Either is a warning. A window
still running is the normal case: a client renews at a random time inside it.

Asked only for CAs of the built-in table, by the ACME directory URL listed there:
nothing the certificate names (an AIA URL, say) decides where the monitoring
service connects. The certificate holder chooses the certificate, not the URL.

One GET per certificate at a time, however many checks or addresses serve it: the
state carries its CertID, and the newest state of a CertID is kept in the process
for the checks that share the certificate. The next GET follows the CA's
Retry-After, clamped to one minute to one day, or six hours without one.
"""

from __future__ import annotations

import base64
import email.utils
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.x509.oid import NameOID

from app.central import fetch
from app.core.time import iso_utc

# RFC 9773 §4.3.2: a Retry-After below one minute or above one day is clamped.
RETRY_MIN = timedelta(minutes=1)
RETRY_MAX = timedelta(days=1)
# §4.3.3: long-term errors (and an answer without Retry-After) wait six hours,
# temporary ones back off exponentially a few times first.
LONG_TERM_WAIT = timedelta(hours=6)
BACKOFF_FIRST = timedelta(minutes=15)
BACKOFF_TRIES = 3
DIRECTORY_TTL = timedelta(days=1)
MAX_TEXT = 200
MAX_REMEMBERED = 1024
_LONG_AGO = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AcmeCa:
    """A CA whose ACME directory is known: its issuer organisation, its CAA identities."""

    name: str
    issuer_orgs: tuple[str, ...]
    directory: str
    caa_identities: tuple[str, ...]


# Directory URLs from each CA's documentation, read from the live directory
# (renewalInfo and caaIdentities) on 2026-11-12. The issuer organisation is the O of
# the intermediates the CA signs with today.
KNOWN_CAS: tuple[AcmeCa, ...] = (
    AcmeCa(
        "Let's Encrypt",
        ("Let's Encrypt",),
        "https://acme-v02.api.letsencrypt.org/directory",
        ("letsencrypt.org",),
    ),
    AcmeCa(
        "Google Trust Services",
        ("Google Trust Services",),
        "https://dv.acme-v02.api.pki.goog/directory",
        ("pki.goog",),
    ),
    AcmeCa(
        "ZeroSSL",
        ("ZeroSSL GmbH",),
        "https://acme.zerossl.com/v2/DV90",
        (
            "sectigo.com",
            "trust-provider.com",
            "usertrust.com",
            "comodoca.com",
            "comodo.com",
            "entrust.net",
            "affirmtrust.com",
        ),
    ),
)

_directory_lock = threading.Lock()
# directory URL -> (renewalInfo URL, fetched at); failures are not kept.
_directories: dict[str, tuple[str, datetime]] = {}
_states_lock = threading.Lock()
# CertID -> the newest state of any check, oldest entry first.
_states: dict[str, dict] = {}


def known_ca(leaf: x509.Certificate) -> AcmeCa | None:
    """The table's CA for the issuer organisation of `leaf`, if any."""
    try:
        orgs = {a.value for a in leaf.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)}
    except ValueError:
        return None
    return next((ca for ca in KNOWN_CAS if orgs.intersection(ca.issuer_orgs)), None)


def cert_id(leaf: x509.Certificate) -> str | None:
    """RFC 9773 §4.1: base64url(AKI keyIdentifier) "." base64url(DER serial), unpadded."""
    try:
        aki = leaf.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
    except (x509.ExtensionNotFound, ValueError):
        return None
    serial = leaf.serial_number
    if not aki.key_identifier or serial < 0:
        return None
    # The DER INTEGER's content octets: big-endian, a leading zero byte when the
    # top bit is set, so the number stays positive.
    der = serial.to_bytes((serial.bit_length() + 8) // 8, "big")
    return f"{_b64url(aki.key_identifier)}.{_b64url(der)}"


def evaluate(
    leaf: x509.Certificate, prev: dict | None, now: datetime
) -> tuple[dict | None, str | None]:
    """The ARI state for the details and a warning, or None when the CA says nothing.

    `prev` is the check's state of its previous run; it counts only for the same
    certificate (RFC 9773 §4.3: a replaced certificate is not asked about again).
    `leaf` is verified and not expired (no queries after the end either). A query
    happens only when the state says one is due.
    """
    ca, cid = known_ca(leaf), cert_id(leaf)
    if ca is None or cid is None:
        return None, None
    state = _latest(cid, prev)
    due = _parse_time(state.get("next_at"))
    if due is None or now >= due:
        state = _refresh(ca, cid, state, now)
        _remember(cid, state)
    start, end = _parse_time(state.get("window_start")), _parse_time(state.get("window_end"))
    if start is None or end is None or now < end:
        return state, None
    warning = (
        f"{ca.name} suggests renewal: window "
        f"{state['window_start']} to {state['window_end']} has passed"
    )
    if state.get("explanation_url"):
        warning += f" ({state['explanation_url']})"
    return state, warning


def _latest(cid: str, prev: dict | None) -> dict:
    """The newer of the check's own state and the process's for this CertID."""
    with _states_lock:
        shared = _states.get(cid)
    known = [s for s in (prev, shared) if isinstance(s, dict) and s.get("cert_id") == cid]
    if not known:
        return {"cert_id": cid}
    return dict(max(known, key=lambda s: _parse_time(s.get("checked_at")) or _LONG_AGO))


def _remember(cid: str, state: dict) -> None:
    with _states_lock:
        _states.pop(cid, None)
        _states[cid] = dict(state)
        while len(_states) > MAX_REMEMBERED:
            del _states[next(iter(_states))]


def _refresh(ca: AcmeCa, cid: str, state: dict, now: datetime) -> dict:
    state["checked_at"] = iso_utc(now)
    try:
        base = _renewal_info_url(ca, now)
        answer = fetch.get(f"{base.rstrip('/')}/{cid}")
    except fetch.FetchError as exc:
        return _failed(state, now, str(exc), temporary=exc.temporary, retry_after=None)
    if answer.status != 200:
        return _failed(
            state,
            now,
            f"renewalInfo: HTTP {answer.status}",
            temporary=answer.status >= 500,
            retry_after=answer.retry_after,
        )
    window = _parse_window(answer.body)
    if window is None:
        # §4.3.3: an invalid RenewalInfo is a long-term error; the last valid
        # window of this certificate stays.
        return _failed(state, now, "renewalInfo: invalid answer", temporary=False, retry_after=None)
    start, end, explanation = window
    wait = _retry_after(answer.retry_after, now)
    state.update(
        window_start=iso_utc(start),
        window_end=iso_utc(end),
        next_at=iso_utc(now + (wait if wait is not None else LONG_TERM_WAIT)),
    )
    state.pop("error", None)
    state.pop("failures", None)
    if explanation:
        state["explanation_url"] = explanation
    else:
        state.pop("explanation_url", None)
    return state


def _failed(
    state: dict, now: datetime, error: str, *, temporary: bool, retry_after: str | None
) -> dict:
    failures = int(state.get("failures") or 0) + 1 if temporary else 0
    wait = _retry_after(retry_after, now)
    if wait is None:
        wait = (
            BACKOFF_FIRST * 2 ** (failures - 1)
            if temporary and failures <= BACKOFF_TRIES
            else LONG_TERM_WAIT
        )
    state.update(error=error[:MAX_TEXT], next_at=iso_utc(now + wait))
    if failures:
        state["failures"] = failures
    else:
        state.pop("failures", None)
    return state


def _renewal_info_url(ca: AcmeCa, now: datetime) -> str:
    with _directory_lock:
        hit = _directories.get(ca.directory)
    if hit is not None and now - hit[1] < DIRECTORY_TTL:
        return hit[0]
    answer = fetch.get(ca.directory)
    if answer.status != 200:
        raise fetch.FetchError(
            f"ACME directory: HTTP {answer.status}", temporary=answer.status >= 500
        )
    try:
        url = json.loads(answer.body)["renewalInfo"]
    except (ValueError, TypeError, KeyError):
        url = None
    if not isinstance(url, str) or not url.startswith("https://"):
        raise fetch.FetchError("ACME directory names no renewalInfo")
    with _directory_lock:
        _directories[ca.directory] = (url, now)
    return url


def _parse_window(body: bytes) -> tuple[datetime, datetime, str | None] | None:
    try:
        data = json.loads(body)
        window = data["suggestedWindow"]
        start = _parse_time(window["start"])
        end = _parse_time(window["end"])
    except (ValueError, TypeError, KeyError):
        return None
    # §4.2: an end not after the start makes the object invalid.
    if start is None or end is None or end <= start:
        return None
    explanation = data.get("explanationURL")
    if not (
        isinstance(explanation, str)
        and explanation.startswith("https://")
        and len(explanation) <= MAX_TEXT
        and explanation.isprintable()
        and " " not in explanation
    ):
        explanation = None
    return start, end, explanation


def _parse_time(value: object) -> datetime | None:
    """An RFC 3339 time with offset; None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        # In UTC here, so that iso_utc and comparisons cannot overflow later.
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _retry_after(value: str | None, now: datetime) -> timedelta | None:
    """Retry-After as seconds or HTTP date (RFC 9110 §10.2.3), clamped; None when absent or invalid."""
    if not value:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        # More digits than a day has seconds is clamped anyway; int() of a header
        # value of thousands of digits would be refused.
        wait = timedelta(seconds=int(value)) if len(value) <= 9 else RETRY_MAX
    else:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if when.tzinfo is None:
            return None
        wait = when - now
    return min(max(wait, RETRY_MIN), RETRY_MAX)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
