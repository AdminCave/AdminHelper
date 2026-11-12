# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenLDAP's slapd from its package or from the image osixia/openldap (R-1242).

The module asks slapd on 389 an anonymous WhoAmI (RFC 4532), which needs no bind and reads
no entry. Any LDAP answer counts, a refusal by the server's access rules too; the check is
critical when slapd refuses or closes the connection, answers no LDAP, or reports itself
busy or unavailable. For the package it also asks StartTLS on 389 once an hour and reads the
certificate slapd presents: warning below 22 days left, critical below 9 or when StartTLS or
the handshake fails. The agent reports days left, not the share of the lifetime (concept
§5); the thresholds are that share of the 90 days an ACME certificate lives. A slapd without
TLS, the Debian default, refuses StartTLS and the certificate check is critical: set up TLS
or turn the check off. On Debian and Ubuntu slapd.service comes from the init script and
stays active when slapd dies, its sub-state exited instead of running; the module rates
that critical, as the protocol check does the closed port. The image (1.5.0:
389 and 636) asks for a client certificate in TLS by default (LDAP_TLS_VERIFY_CLIENT
demand), so the module reads the certificate of the package only.

Not covered: replication (contextCSN) and cn=Monitor, a slapd that listens on LDAPS or ldapi
only (both checks critical: turn them off), the certificate inside the image, the image's
pre-releases from 2.6 on (3890 and 6360: the check is not bound), the discontinued image
bitnami/openldap, and other LDAP servers (389 Directory Server, Samba AD).
"""

_ANSWERS_FIELDS = ["ok", "detail", "duration_ms"]
_ANSWERS_RULES = [{"field": "ok", "op": "eq", "value": False, "level": "critical"}]

MODULE = {
    "id": "openldap",
    "name": "OpenLDAP",
    "version": 1,
    "description": (
        "OpenLDAP's slapd from its package or image: the unit or the container, whether slapd "
        "answers LDAP, and for the package the certificate behind StartTLS."
    ),
    "detect": {
        "container_images": ["osixia/openldap"],
        "units": ["slapd.service"],
    },
    "instance": "compose_project",
    "checks": [
        {
            "key": "container",
            "name": "Container",
            "sensor": "container",
            "target": {"kind": "container"},
            "interval": 300,
            "fields": ["state", "health", "restarts"],
            "rules": [
                {"field": "state", "op": "ne", "value": "running", "level": "critical"},
                {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
            ],
        },
        {
            "key": "answers",
            "name": "slapd answers",
            "sensor": "proto",
            "target": {"kind": "container", "port_hint": 389},
            "params": {"protocol": "ldap"},
            "interval": 300,
            "fields": _ANSWERS_FIELDS,
            "rules": _ANSWERS_RULES,
        },
        {
            "key": "service",
            "name": "Service",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"},
                # The unit the init script gives (RemainAfterExit=yes, no main PID).
                {"field": "sub_state", "op": "eq", "value": "exited", "level": "critical"},
            ],
        },
        {
            "key": "service_answers",
            "name": "slapd answers (service)",
            "sensor": "proto",
            "target": {"kind": "unit", "port_hint": 389},
            "params": {"protocol": "ldap"},
            "interval": 300,
            "fields": _ANSWERS_FIELDS,
            "rules": _ANSWERS_RULES,
        },
        {
            "key": "certificate",
            "name": "Certificate (StartTLS)",
            "sensor": "tls",
            "target": {"kind": "unit", "port_hint": 389},
            "params": {"starttls": "ldap"},
            "interval": 3600,
            "fields": ["days_left", "not_after", "issuer", "chain_ok"],
            "rules": [
                {"field": "days_left", "op": "lt", "value": 22, "level": "warning"},
                {"field": "days_left", "op": "lt", "value": 9, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "answers", "field": "detail", "label": "LDAP"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_answers", "field": "detail", "label": "LDAP"},
        {"check_key": "certificate", "field": "days_left", "label": "Certificate days left"},
    ],
}
