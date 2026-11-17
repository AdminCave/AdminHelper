# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Samba as an Active Directory domain controller, from its unit (R-1240).

The module is found by samba-ad-dc.service (Debian, Ubuntu, linuxmuster.net). Every 15 minutes
the agent's app sensor reads the replication links of this DC from samba-tool drs showrepl
--json: the partners, the inbound links, those failing and the outbound links failing, and the
age of the oldest last success of an inbound link. A failing link warns, a last success older
than 12 hours is critical (concept §6.3). The only DC of its domain pulls from nobody: the agent
reports an age of 0 there, an agent before that none, and the check stays unknown (R-1491). Every
15 minutes the agent counts smbd, nmbd and winbind (smb, nmb on Fedora) active beside the DC,
which warns: the samba service starts its own, and a separate one makes the DC fail (Samba wiki,
"Managing the Samba AD DC Service Using Systemd"). Every hour the agent reads the realm from
testparm -s and asks the resolver of the host for the five SRV records every writable DC
registers (source4/setup/dns_update_list: _ldap._tcp, _kerberos._tcp, _kerberos._udp,
_ldap._tcp.dc._msdcs, _kerberos._tcp.dc._msdcs); one missing warns. It asks whether the domain
has them, not whether this DC is among their targets. Once a day samba-tool fsmo show counts
the FSMO roles and those without a valid owner, which warns. Once an hour the agent reads the
certificate behind LDAPS on 636: warning below 25 % of its lifetime left, critical below 10 %
or 12 hours. Samba's self-signed certificate is valid for 700 days, so the share and not a
number of days rates it. No DC name, DN or partner leaves the host; samba-tool dbcheck is never
run.

Not covered: the clock offset against the partners.
"""

MODULE = {
    "id": "samba-ad-dc",
    "name": "Samba AD DC",
    "version": 2,
    "description": (
        "Samba as an Active Directory domain controller: the unit, the replication links, the "
        "units beside the DC, the SRV records, the FSMO owners and the certificate behind LDAPS."
    ),
    "detect": {"units": ["samba-ad-dc.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Service",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "replication",
            "name": "Replication",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "samba_drs"},
            "interval": 900,
            "fields": [
                "partners",
                "links",
                "links_failing",
                "outbound_failing",
                "last_success_age_s",
            ],
            "rules": [
                {"field": "links_failing", "op": "gt", "value": 0, "level": "warning"},
                {"field": "outbound_failing", "op": "gt", "value": 0, "level": "warning"},
                {"field": "last_success_age_s", "op": "gt", "value": 43200, "level": "critical"},
            ],
        },
        {
            "key": "side_units",
            "name": "Units beside the DC",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "samba_dc_units"},
            "interval": 900,
            "fields": ["side_units_active"],
            "rules": [{"field": "side_units_active", "op": "gt", "value": 0, "level": "warning"}],
        },
        {
            "key": "dns",
            "name": "SRV records",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "samba_dns"},
            "interval": 3600,
            "fields": ["srv_checked", "srv_missing"],
            "rules": [{"field": "srv_missing", "op": "gt", "value": 0, "level": "warning"}],
        },
        {
            "key": "fsmo",
            "name": "FSMO roles",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "samba_fsmo"},
            "interval": 86400,
            "fields": ["roles", "roles_without_owner"],
            "rules": [{"field": "roles_without_owner", "op": "gt", "value": 0, "level": "warning"}],
        },
        {
            "key": "certificate",
            "name": "Certificate (LDAPS)",
            "sensor": "tls",
            "target": {"kind": "unit", "port_hint": 636},
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
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "replication", "field": "partners", "label": "Partners"},
        {"check_key": "replication", "field": "links_failing", "label": "Links failing"},
        {"check_key": "replication", "field": "last_success_age_s", "label": "Last success s"},
        {"check_key": "fsmo", "field": "roles_without_owner", "label": "FSMO without owner"},
        {"check_key": "certificate", "field": "days_left", "label": "Certificate days left"},
    ],
}
