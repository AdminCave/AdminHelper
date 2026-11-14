# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenLDAP's slapd from its package or from the image osixia/openldap (R-1242, R-1404).

The module asks slapd on 389 an anonymous WhoAmI (RFC 4532), which needs no bind and reads
no entry. Any LDAP answer counts, a refusal by the server's access rules too; the check is
critical when slapd refuses or closes the connection, answers no LDAP, or reports itself
busy or unavailable. For the package it also asks StartTLS on 389 once an hour and reads the
certificate slapd presents: warning below 25 % of its lifetime left, critical below 10 % or
12 hours, or when StartTLS or the handshake fails (concept §5). A slapd without
TLS, the Debian default, refuses StartTLS and the certificate check is critical: set up TLS
or turn the check off. On Debian and Ubuntu slapd.service comes from the init script and
stays active when slapd dies, its sub-state exited instead of running; the module rates
that critical, as the protocol check does the closed port. The image (1.5.0:
389 and 636) asks for a client certificate in TLS by default (LDAP_TLS_VERIFY_CLIENT
demand), so the module reads the certificate of the package only.

For the package the agent's app sensor (R-1404) reads the replication state every five
minutes over slapd's ldapi socket, bound with SASL EXTERNAL as the agent's user: the naming
contexts with a contextCSN and the age of the newest CSN, and, where cn=Monitor (back-monitor)
is set up and readable for that user, the syncrepl consumers below cn=Databases,cn=Monitor,
those without a connection to their provider and those not in the persist phase. It never
asks for the providers' addresses. A consumer without a connection warns. Without
cn=Monitor, the Debian default, the agent reports monitor false without the consumer counts
and the check stays unknown: set up cn=Monitor or turn the check off. The card shows the
replication in place of the container's health: the image has no HEALTHCHECK of its own.

Not covered: the lag between provider and consumer across hosts (the agent asks no other
host), replication inside the image (its ldapi socket lives in the container), a slapd that
listens on LDAPS or ldapi only (both protocol checks critical: turn them off), the
certificate inside the image, the image's pre-releases from 2.6 on (3890 and 6360: the
check is not bound), the discontinued image bitnami/openldap, and other LDAP servers (389
Directory Server, Samba AD).
"""

_ANSWERS_FIELDS = ["ok", "detail", "duration_ms"]
_ANSWERS_RULES = [{"field": "ok", "op": "eq", "value": False, "level": "critical"}]

MODULE = {
    "id": "openldap",
    "name": "OpenLDAP",
    "version": 3,
    "description": (
        "OpenLDAP's slapd from its package or image: the unit or the container, whether slapd "
        "answers LDAP, and for the package the certificate behind StartTLS and the state of "
        "its replication."
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
            "fields": [
                "days_left",
                "hours_left",
                "lifetime_pct",
                "not_after",
                "issuer",
                "chain_ok",
            ],
            "rules": [
                {"field": "lifetime_pct", "op": "lt", "value": 25, "level": "warning"},
                {"field": "lifetime_pct", "op": "lt", "value": 10, "level": "critical"},
                {"field": "hours_left", "op": "lt", "value": 12, "level": "critical"},
            ],
        },
        {
            "key": "replication",
            "name": "Replication",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "ldap_replication"},
            "interval": 300,
            "fields": [
                "contexts",
                "csn_age_s",
                "monitor",
                "consumers",
                "disconnected",
                "refreshing",
            ],
            "rules": [{"field": "disconnected", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "answers", "field": "detail", "label": "LDAP"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_answers", "field": "detail", "label": "LDAP"},
        {"check_key": "certificate", "field": "days_left", "label": "Certificate days left"},
        {"check_key": "replication", "field": "disconnected", "label": "Replication"},
    ],
}
