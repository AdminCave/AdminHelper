# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""What of the FRP server config frps is started with: the extra_config entries, and the
values of the string fields the generator writes into frps.toml.

The frps supervisor (apps/frps/frps-supervisor.sh) starts frps only from a frps.toml
whose top-level keys are all in its TOP_KEYS and whose lines follow its grammar
(check_config); any other key or value leaves frps without a config to start from.
The list belongs to the script: ALLOWED_KEYS is the same list minus the keys
config_generator writes itself, and tests/test_frp_extra_config.py holds the two
together.
"""

import math

# TOP_KEYS without bindPort, vhostHTTPSPort, subDomainHost, maxPortsPerClient,
# detailedErrorsToClient, webServer.* and auth.*: generate_frps_toml writes those from
# their own fields, the optional ones whenever their field is set, and the supervisor
# rejects a key that appears twice.
ALLOWED_KEYS = frozenset(
    {
        "transport.maxPoolCount",
        "transport.tcpMux",
        "transport.tcpMuxKeepaliveInterval",
        "transport.heartbeatTimeout",
        "transport.tcpKeepalive",
        "userConnTimeout",
        "log.level",
        "log.maxDays",
    }
)

# The string fields of the config generate_frps_toml writes into frps.toml, by their key
# there; their values follow value_allowed like a string in extra_config.
STRING_FIELDS = {
    "subDomainHost": "subdomain_host",
    "webServer.user": "dashboard_user",
    "webServer.password": "dashboard_password",
    "auth.token": "auth_token",
}


def value_allowed(value: object) -> bool:
    """Whether the line the generator writes for value follows check_config's grammar:
    true, false, a number, or a string without quotes, backslashes, braces or control
    characters. A string with a lone surrogate (U+D800 to U+DFFF) has no UTF-8 form, so
    frps.toml cannot carry its line at all."""
    if isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        # The generator writes nan and inf as such, and the grammar has no place for them.
        return math.isfinite(value)
    if isinstance(value, str):
        return not any(
            c in '"\\{}' or ord(c) < 0x20 or c == "\x7f" or "\ud800" <= c <= "\udfff" for c in value
        )
    return False


def rejected_keys(extra: dict) -> list[str]:
    """The keys of extra that frps would not be started with: not allowed, or with a
    value outside the grammar."""
    return [
        key for key, value in extra.items() if key not in ALLOWED_KEYS or not value_allowed(value)
    ]
