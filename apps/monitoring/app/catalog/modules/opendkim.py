# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenDKIM from its unit (R-1239).

The module is found by opendkim.service. Once a day the agent's app sensor tests the keys of
the KeyTable against their records in the DNS with opendkim-testkey -v and counts them and
those that fail, from its summary; a key that fails warns: receivers may reject the signed
mail. Which key fails and why stays on the host, as do selectors and domains.

Not covered: OpenDKIM without a KeyTable (a single KeyFile), and the DKIM of Rspamd or Mailcow.
"""

MODULE = {
    "id": "opendkim",
    "name": "OpenDKIM",
    "version": 1,
    "description": (
        "OpenDKIM from its unit: the unit and once a day the keys of its KeyTable against "
        "their records in the DNS."
    ),
    "detect": {"units": ["opendkim.service"]},
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
            "key": "keys",
            "name": "Keys",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "opendkim_keys"},
            "interval": 86400,
            "fields": ["keys", "keys_failed"],
            "rules": [{"field": "keys_failed", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "keys", "field": "keys", "label": "Keys"},
        {"check_key": "keys", "field": "keys_failed", "label": "Keys failing"},
    ],
}
