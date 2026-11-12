# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CAA (RFC 8659) for the sensor tls: may the current issuer issue the next certificate? (R-1224)

The relevant record set is the first non-empty one on the way from the name up to
the top-level domain; the resolver follows a CNAME, the parents of its target are
not climbed (RFC 8659 §3). Asked over the public resolvers directly, like the rule
public/internal: what they answer is what the CA will see. Only for an issuer of
the ACME table, whose CAA identities are known; for any other there is no statement.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import dns.exception
import dns.name
import dns.resolver
from cryptography import x509

from app.central import resolve
from app.central.ari import AcmeCa
from app.central.resolve import AnswerStatus
from app.core import config
from app.core.time import iso_utc

RECHECK = timedelta(days=1)
RETRY_NO_ANSWER = timedelta(hours=1)
# Names of more labels get no statement rather than one query per label.
MAX_LABELS = 16
MAX_LISTED = 10
CRITICAL_FLAG = 0x80
KNOWN_TAGS = frozenset({"issue", "issuewild", "iodef"})

# RFC 8659 §4.2, issue-value. Classes written out: the grammar is ASCII only.
_LABEL = r"[A-Za-z0-9](?:-*[A-Za-z0-9])*"
_PARAMETER = _LABEL + r"[ \t]*=[ \t]*[\x21-\x3a\x3c-\x7e]*"
_ISSUE_VALUE = re.compile(
    rf"[ \t]*(?P<domain>{_LABEL}(?:\.{_LABEL})*)?[ \t]*"
    rf"(?:;[ \t]*(?:{_PARAMETER}(?:[ \t]*;[ \t]*{_PARAMETER})*[ \t]*)?)?"
)


@dataclass(frozen=True)
class Record:
    flags: int
    tag: str
    value: str


@dataclass(frozen=True)
class CaaAnswer:
    status: AnswerStatus
    records: tuple[Record, ...] = ()


class _NoStatement(Exception):
    pass


def query(resolver: str, name: dns.name.Name) -> CaaAnswer:
    """Asks `resolver` for the CAA records of `name`; tests replace this function."""
    res = dns.resolver.Resolver(configure=False)
    res.nameservers = [resolver]
    res.lifetime = resolve.QUERY_LIFETIME_S
    try:
        answer = res.resolve(name, "CAA", raise_on_no_answer=False, search=False)
    except dns.resolver.NXDOMAIN:
        return CaaAnswer(AnswerStatus.NXDOMAIN)
    except (dns.exception.DNSException, OSError):
        return CaaAnswer(AnswerStatus.SILENT)
    if answer.rrset is None:
        return CaaAnswer(AnswerStatus.NODATA)
    return CaaAnswer(
        AnswerStatus.OK,
        tuple(
            # Tags compare without regard to case (RFC 8659 §4.1); a byte outside
            # ASCII breaks the grammar, and the replacement character keeps it broken.
            Record(
                r.flags,
                r.tag.decode("ascii", "replace").lower(),
                r.value.decode("ascii", "replace"),
            )
            for r in answer.rrset
        ),
    )


def evaluate(
    leaf: x509.Certificate,
    host: str,
    ca: AcmeCa | None,
    prev: dict | None,
    now: datetime,
    resolvers: tuple[str, ...] | None = None,
) -> tuple[dict | None, str | None]:
    """The CAA state for the details and a warning, or None without a statement.

    `prev` is the check's state of its previous run; it counts only for the same
    name, wildcard and CA. Asked again once a day, an hour after the resolvers gave
    no answer; in between the stored verdict holds.
    """
    target = _subject(leaf, host) if ca is not None else None
    if ca is None or target is None:
        return None, None
    key = {"subject": target[0], "wildcard": target[1], "ca": ca.name}
    same = isinstance(prev, dict) and all(prev.get(k) == v for k, v in key.items())
    state = dict(prev) if same else key
    due = _parse_time(state.get("next_at"))
    if due is None or now >= due:
        state = _refresh(state, key, ca, now, resolvers or config.PUBLIC_RESOLVERS)
    if state.get("permitted") is not False:
        return state, None
    found = state.get("name")
    if state.get("critical_tag"):
        return state, (
            f"CAA of {found} carries the unknown critical tag {state['critical_tag']}: "
            "no CA may issue"
        )
    allowed = ", ".join(state.get("allowed") or []) or "nobody"
    return state, f"CAA of {found} does not permit {ca.name} (permitted: {allowed})"


def relevant_set(domain: str, resolvers: tuple[str, ...]) -> tuple[str | None, tuple[Record, ...]]:
    """The first non-empty CAA set from `domain` up to its TLD; (None, ()) when there is none."""
    labels = domain.split(".")
    if len(labels) > MAX_LABELS:
        raise _NoStatement(f"more than {MAX_LABELS} labels")
    for i in range(len(labels)):
        candidate = ".".join(labels[i:])
        answer = _ask(candidate, resolvers)
        if answer.status is AnswerStatus.OK:
            return candidate, answer.records
    return None, ()


def permitted_issuers(
    records: tuple[Record, ...], wildcard: bool
) -> tuple[tuple[str, ...] | None, str | None]:
    """The issuer domains the set permits (None: no restriction) and an unknown critical tag."""
    critical = next(
        (r.tag for r in records if r.flags & CRITICAL_FLAG and r.tag not in KNOWN_TAGS), None
    )
    # issuewild only for a wildcard, and there it replaces every issue (RFC 8659 §4.3).
    properties = [r for r in records if r.tag == "issuewild"] if wildcard else []
    if not properties:
        properties = [r for r in records if r.tag == "issue"]
    if not properties:
        return None, critical
    # A value outside the grammar permits nobody, as an empty issuer does (§4.2).
    issuers = (_issuer(r.value) for r in properties)
    return tuple(dict.fromkeys(i for i in issuers if i)), critical


def _refresh(state: dict, key: dict, ca: AcmeCa, now: datetime, resolvers: tuple[str, ...]) -> dict:
    try:
        found, records = relevant_set(key["subject"], resolvers)
    except _NoStatement as exc:
        # The last verdict stays until an answer comes.
        state.update(
            checked_at=iso_utc(now), error=str(exc), next_at=iso_utc(now + RETRY_NO_ANSWER)
        )
        return state
    allowed, critical = permitted_issuers(records, key["wildcard"])
    state = {
        **key,
        "checked_at": iso_utc(now),
        "next_at": iso_utc(now + RECHECK),
        "name": found,
        "allowed": None if allowed is None else list(allowed[:MAX_LISTED]),
        "permitted": critical is None
        and (allowed is None or any(i in allowed for i in ca.caa_identities)),
    }
    if critical:
        state["critical_tag"] = critical[:32]
    return state


def _ask(name: str, resolvers: tuple[str, ...]) -> CaaAnswer:
    try:
        qname = dns.name.from_text(name)
    except (dns.exception.DNSException, UnicodeError):
        raise _NoStatement("invalid name") from None
    for resolver in resolvers:
        answer = query(resolver, qname)
        if answer.status is not AnswerStatus.SILENT:
            return answer
    raise _NoStatement(resolve.RESOLVERS_UNREACHABLE_MESSAGE)


def _subject(leaf: x509.Certificate, host: str) -> tuple[str, bool] | None:
    """The name CAA is looked up for and whether the certificate covers `host` by a wildcard."""
    try:
        ipaddress.ip_address(host)
        return None  # CAA is for domain names
    except ValueError:
        pass
    try:
        sans = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = {n.lower() for n in sans.get_values_for_type(x509.DNSName)}
    except (x509.ExtensionNotFound, ValueError):
        return None
    host = host.lower()
    if host in names:
        return host, False
    parent = host.partition(".")[2]
    if parent and f"*.{parent}" in names:
        return parent, True
    return None


def _issuer(value: str) -> str | None:
    match = _ISSUE_VALUE.fullmatch(value)
    domain = match["domain"] if match else None
    return domain.lower() if domain else None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None
