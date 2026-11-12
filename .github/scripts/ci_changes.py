#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which gated suites of ci.yml a pull request needs, from the paths it changes (R-1340).

Prints one name=value line for each output of the job changes (ci.yml), for $GITHUB_OUTPUT:
true or false for each suite, and server-legs, the Python versions of the server job as a JSON list.

Only a pull request is narrowed: EVENT=pull_request reads the paths the pull request changes
on top of its base (git diff origin/$BASE_REF...$SHA). Every other event runs every suite, and
so does a pull request that changes no path at all or a path outside the narrow areas: a root
file, .github/, scripts/ or anything new. Inside them a suite runs when a path matches its
scope, which names its own component and every file outside of it its tests read
(test_ci_changes.py holds it in step with them). On a pull request the server suite runs on
one Python only, on main both.

Patterns: ** matches any characters, * any but /; a leading ! takes a path out again, and the
last pattern that matches a path decides, as in .gitignore.
"""

import json
import os
import re
import subprocess
import sys

LEGS = ("3.14", "3.15")
PR_LEGS = ("3.14",)

# A path outside these areas turns every suite on.
NARROW = (
    "apps/agent/**",
    "apps/ca-issuer/**",
    "apps/desktop/**",
    "apps/frps/**",
    "apps/gateway/**",
    "apps/monitoring/**",
    "apps/server/**",
    "apps/web/**",
    "docs/**",
    # Nearly every pull request carries its ledger and a changelog fragment; no suite reads them.
    "tasks/**",
    "changelog.d/**",
)

# The files apps/frps/Dockerfile.dockerignore lets into the build context of the frps image,
# which the server tests build.
_FRPS_CONTEXT = (
    "apps/agent/go.mod",
    "apps/agent/go.sum",
    "apps/agent/cmd/frps-policy/**",
    "apps/agent/internal/frpspolicy/**",
)

SCOPES = {
    "server": (
        "apps/server/**",
        "apps/gateway/**",
        "apps/frps/**",
        *_FRPS_CONTEXT,
        # the frpc configuration the agent expects, which the config generator must produce
        "apps/agent/internal/frpc/testdata/**",
        "apps/ca-issuer/**",
        "!apps/ca-issuer/tests/**",
        "apps/monitoring/**",
        "!apps/monitoring/tests/**",
        "apps/web/src/lib/**",
        "apps/desktop/src-tauri/src/tunnel.rs",
        "docs/examples/**",
        "docs/developer/api-reference.html",
        "docs/developer/monitoring.html",
        "docs/en/developer/api-reference.html",
        "docs/en/developer/monitoring.html",
    ),
    "monitoring": (
        "apps/monitoring/**",
        "apps/server/app/modules/notifications/schemas.py",
        "apps/desktop/ui/src/components/monitoring/section/SecServices.svelte",
        "apps/desktop/ui/src/lib/models/monitoring.ts",
        "apps/agent/internal/monitor/hostfacts.go",
    ),
    "ca-issuer": ("apps/ca-issuer/**",),
    "schemathesis": ("apps/server/**", "apps/monitoring/**", "apps/ca-issuer/**"),
    # The image lock jobs run the suites against the hashed lock the image installs; on a pull
    # request only when the lock or the image changes (the server image is the root Dockerfile,
    # outside the narrow areas). Kevin's trade-off: a lock-only failure surfaces on main.
    "lock-server": ("apps/server/requirements*",),
    "lock-monitoring": ("apps/monitoring/requirements*", "apps/monitoring/Dockerfile"),
    "lock-ca-issuer": ("apps/ca-issuer/requirements*", "apps/ca-issuer/Dockerfile"),
    # Not docs/**, which docs_cli_test.go reads: the Windows-only sources add no command and no
    # flag, and the agent job checks the same command tree on every pull request.
    "agent-windows": ("apps/agent/**",),
    "rust-windows": (
        "apps/desktop/src-tauri/**",
        # include_str! in src/connection/ssh.rs
        "apps/agent/internal/credentials/store.go",
        "apps/agent/internal/allowlist/allowlist.go",
    ),
}


def _regex(pattern: str) -> re.Pattern[str]:
    parts = re.split(r"(\*\*|\*)", pattern)
    table = {"**": ".*", "*": "[^/]*"}
    return re.compile("".join(table.get(part, re.escape(part)) for part in parts))


def matches(patterns: tuple[str, ...], path: str) -> bool:
    hit = False
    for pattern in patterns:
        if _regex(pattern.removeprefix("!")).fullmatch(path):
            hit = not pattern.startswith("!")
    return hit


def outputs(event: str, paths: list[str]) -> tuple[dict[str, str], list[str]]:
    """The output lines of the job changes and, for the log, why each suite runs."""
    if event != "pull_request":
        wanted = {name: f"event {event} runs everything" for name in SCOPES}
    elif not paths:
        wanted = {name: "no changed path, which runs everything" for name in SCOPES}
    elif outside := next((path for path in paths if not matches(NARROW, path)), None):
        wanted = {name: f"{outside} lies outside the narrow areas" for name in SCOPES}
    else:
        wanted = {}
        for name, patterns in SCOPES.items():
            path = next((path for path in paths if matches(patterns, path)), None)
            if path is not None:
                wanted[name] = path
    result = {name: "true" if name in wanted else "false" for name in SCOPES}
    legs = PR_LEGS if event == "pull_request" else LEGS
    result["server-legs"] = json.dumps(list(legs), separators=(",", ":"))
    reasons = [f"{name}: {wanted.get(name, 'no changed path in its scope')}" for name in SCOPES]
    return result, reasons


def changed_paths(base_ref: str, sha: str) -> list[str]:
    # --no-renames: a rename counts as its old and its new path.
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"origin/{base_ref}...{sha}"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return [path for path in diff.stdout.split("\0") if path]


def main() -> int:
    event = os.environ["EVENT"]
    paths = (
        changed_paths(os.environ["BASE_REF"], os.environ["SHA"]) if event == "pull_request" else []
    )
    result, reasons = outputs(event, paths)
    print(f"{len(paths)} changed paths", file=sys.stderr)
    for reason in reasons:
        print(reason, file=sys.stderr)
    for name, value in result.items():
        print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
