# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenAPI snapshot of the monitoring API (harness 8a, T8).

Same guard as the server's (tests/test_openapi_snapshot.py), for the service the
server proxies to: every route here is consumed through /api/monitoring/* by the
web frontend and the desktop UI, and a changed field reaches them only at
runtime. The snapshot makes it a review diff, and oasdiff compares against it.

    pytest tests/test_openapi_snapshot.py --update-openapi-snapshot

and the rewritten file belongs in the SAME commit as the API change.
"""

import difflib
import json
from pathlib import Path

_SNAPSHOT = Path(__file__).resolve().parent / "openapi.snapshot.json"


def _current_schema() -> str:
    from app.main import app

    # Deep-copy through JSON: app.openapi() memoizes on the app object.
    spec = json.loads(json.dumps(app.openapi()))
    spec.setdefault("info", {})["version"] = "0.0.0"
    spec.pop("servers", None)
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_openapi_matches_snapshot(pytestconfig):
    current = _current_schema()

    if pytestconfig.getoption("--update-openapi-snapshot"):
        _SNAPSHOT.write_text(current, encoding="utf-8")

    assert _SNAPSHOT.exists(), (
        f"{_SNAPSHOT.name} is missing — create it with "
        f"`pytest tests/test_openapi_snapshot.py --update-openapi-snapshot`"
    )
    stored = _SNAPSHOT.read_text(encoding="utf-8")

    if stored != current:
        diff = list(
            difflib.unified_diff(
                stored.splitlines(),
                current.splitlines(),
                fromfile="openapi.snapshot.json",
                tofile="app.openapi()",
                lineterm="",
            )
        )
        raise AssertionError(
            "the monitoring service's OpenAPI schema changed.\n"
            "If that is intended, re-record it IN THE SAME COMMIT:\n"
            "    pytest tests/test_openapi_snapshot.py --update-openapi-snapshot\n\n"
            + "\n".join(diff[:40])
        )


def test_snapshot_covers_the_api():
    """Non-empty guard: a snapshot taken from an app that failed to mount its
    routers would compare two empty schemas and pass."""
    paths = json.loads(_SNAPSHOT.read_text(encoding="utf-8")).get("paths", {})
    assert len(paths) >= 20, f"snapshot holds only {len(paths)} paths"
