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

The developer docs (monitoring.html, DE + EN) enumerate the same prefixes, and
that enumeration drifted the same way (R-0382), so it is pinned to the tuple too.
"""

import re
from pathlib import Path

from app.modules.monitoring_proxy.router import _ALLOWED_PATH_PREFIXES

_REPO = Path(__file__).resolve().parents[3]
_ROUTERS_DIR = _REPO / "apps" / "monitoring" / "app" / "routers"
# \s* spans newlines, so a decorator broken across lines by ruff format counts too.
_ROUTE = re.compile(r'@router\.(?:get|post|put|delete|patch)\(\s*"([^"]+)"')
# Every route decorator, whatever its shape. A route the scan above cannot read —
# an api_route, a path in a constant — would be missing from BOTH sides of the
# equality below, so the test would agree on an incomplete set while the route is
# unreachable through the proxy.
_ANY_ROUTE_DECORATOR = re.compile(r"@router\.\w+\(")

# Reached directly via X-Internal-Key, not through the browser-facing proxy.
_INTERNAL_ONLY = {"agent-keys", "servers"}

# The words that introduce the prefix enumeration on each page. Only the
# comma-separated <code> run right after them is read: the page names `status`
# and `maintenance` elsewhere too, so a prefix dropped from this one list would
# still be found somewhere on the page.
_PREFIX_DOCS = {
    "docs/developer/monitoring.html": "erlaubte Pfad-Prefixe sind",
    "docs/en/developer/monitoring.html": "allowed path prefixes are",
}
_CODE_RUN = re.compile(r"\s*((?:<code>[^<]+</code>(?:,\s*)?)+)")


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


def _documented_prefixes(page: str, anchor: str) -> list[str]:
    text = (_REPO / page).read_text(encoding="utf-8")
    # Exactly once: a reworded sentence must fail here, not leave nothing to compare.
    assert text.count(anchor) == 1, (
        f"{page}: expected the prefix sentence {anchor!r} once, found {text.count(anchor)}"
    )
    run = _CODE_RUN.match(text, text.index(anchor) + len(anchor))
    assert run, f"{page}: no <code> list after {anchor!r}"
    return re.findall(r"<code>([^<]+)</code>", run.group(1))


def test_docs_enumerate_exactly_the_allowlist():
    """Sorted, not as sets: a prefix listed twice is drift as well."""
    expected = sorted(_ALLOWED_PATH_PREFIXES)
    documented = {
        page: sorted(_documented_prefixes(page, anchor)) for page, anchor in _PREFIX_DOCS.items()
    }
    assert documented == {page: expected for page in _PREFIX_DOCS}, (
        f"prefix list in the developer docs drifted from _ALLOWED_PATH_PREFIXES {expected}: "
        f"{documented}"
    )
