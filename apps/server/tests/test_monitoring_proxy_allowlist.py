# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Proxy allowlist / monitoring route consistency (harness 8a, T1).

_ALLOWED_PATH_PREFIXES is the server's SSRF guard for /api/monitoring/*: a
prefix that no monitoring route serves is dead weight, and a monitoring route
whose prefix is missing is unreachable from the browser. Both drifted — `log`
and `metrics` were in the list although the real routes are `alerts/log` and
`checks/{id}/metrics`. Pin the two sides to exact equality.

The two server-internal prefixes are excluded by name: they are called with
X-Internal-Key straight against the monitoring service, never through the proxy
(provisioning/helpers.py, servers/router.py). Only `routers/*.py` is scanned —
a route defined on the app itself (today just main.py's /health) is not
proxyable and deliberately outside this contract.
"""

import re
from pathlib import Path

from app.modules.monitoring_proxy.router import _ALLOWED_PATH_PREFIXES

_ROUTERS_DIR = Path(__file__).resolve().parents[3] / "apps" / "monitoring" / "app" / "routers"
# \s* spans newlines, so a decorator broken across lines by ruff format counts too.
_ROUTE = re.compile(r'@router\.(?:get|post|put|delete|patch)\(\s*"([^"]+)"')
# Every route decorator, whatever its shape. A route the scan above cannot read —
# an api_route, a path in a constant — would be missing from BOTH sides of the
# equality below, so the test would agree on an incomplete set while the route is
# unreachable through the proxy.
_ANY_ROUTE_DECORATOR = re.compile(r"@router\.\w+\(")

# Reached directly via X-Internal-Key, not through the browser-facing proxy.
_INTERNAL_ONLY = {"agent-keys", "servers"}


def _monitoring_first_segments() -> set[str]:
    segments: set[str] = set()
    for py in sorted(_ROUTERS_DIR.glob("*.py")):
        for path in _ROUTE.findall(py.read_text(encoding="utf-8")):
            first = path.lstrip("/").split("/", 1)[0]
            if first:
                segments.add(first)
    return segments


def test_allowlist_matches_monitoring_routes():
    segments = _monitoring_first_segments()
    # Sanity: the decorator scan actually read the routers (an empty parse would
    # otherwise make every assertion below vacuously true).
    assert len(segments) >= 5, f"route scan found too few segments: {sorted(segments)}"

    proxied = segments - _INTERNAL_ONLY
    assert proxied == set(_ALLOWED_PATH_PREFIXES), (
        f"proxy allowlist drifted from the monitoring routes — "
        f"unreachable routes: {sorted(proxied - set(_ALLOWED_PATH_PREFIXES))}, "
        f"dead allowlist entries: {sorted(set(_ALLOWED_PATH_PREFIXES) - proxied)}"
    )


def test_every_route_decorator_is_readable():
    """A decorator the literal scan misses would make the comparison vacuous for
    exactly the route that was just added."""
    for py in sorted(_ROUTERS_DIR.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        declared = len(_ANY_ROUTE_DECORATOR.findall(text))
        read = len(_ROUTE.findall(text))
        assert declared == read, (
            f"{py.name}: {declared} route decorators, {read} readable — a route "
            f"declared some other way (api_route, a path in a constant) is invisible "
            f"to this guard and would be unreachable through the proxy"
        )


def test_internal_only_exclusions_still_exist():
    """The exclusion list is only correct while those routes exist — if one is
    renamed or dropped, the entry above has to go too, not linger as a hole."""
    segments = _monitoring_first_segments()
    assert _INTERNAL_ONLY <= segments, (
        f"exclusions name routes the monitoring service no longer has: "
        f"{sorted(_INTERNAL_ONLY - segments)}"
    )
