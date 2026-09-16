#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""doc-smoke.py — does the documentation still describe this repository?

    python3 scripts/dev/doc-smoke.py [--paths] [--env] [--strict] [--root <dir>]

Two checks over every ``<code>…</code>`` in ``docs/**/*.html``:

  --paths  (default)  a fragment that starts with apps/, scripts/, docs/,
                      .github/ or .claude/ names a file or directory that
                      exists. Renaming a file and leaving the docs behind is
                      the single most common way this documentation goes stale,
                      and nothing has ever checked it.
  --env               an ALL_CAPS fragment that looks like an environment
                      variable is known to at least one of the three config.py
                      files or to .env.example. Only names no source knows at
                      all are reported — a variable read by one service and
                      documented for another is not drift.

Exceptions live in scripts/dev/doc-smoke-allow.txt, one entry per line with a
reason after '#'; the file is shared by both checks, so an entry silences a path
and an identically spelled env name alike. The file is capped at 5 entries on purpose: an exception list
is where a check like this goes to rot, so once it grows past a handful the
answer is to fix the documentation, not to extend the list.

Exit codes: 0 clean · 1 findings (under --strict) · 2 the allowlist is too long
or the arguments are wrong. Without --strict findings are printed and the exit
stays 0, so the check can be run for information before it is a gate.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# <code class="…"> counts too: the guard must not lose coverage the day
# someone adds a highlight class.
_CODE = re.compile(r"<code\b[^>]*>(.*?)</code>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_PATH_PREFIXES = ("apps/", "scripts/", "docs/", ".github/", ".claude/")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")
_ALLOW_MAX = 5
# The floor is a non-empty guard, not a quota: a parser that quietly loses most of
# its coverage has to be caught too, so it sits near the real number (62 today)
# rather than near zero. Lower it only after confirming the documentation, not the
# parser, is what changed.
_PATH_FLOOR = 45

# Read as environment names from the app configuration, plus .env.example keys
# (active or commented out — a commented example still documents the name).
_CONFIGS = (
    "apps/server/app/core/config.py",
    "apps/monitoring/app/core/config.py",
    "apps/ca-issuer/app/config.py",
)
_ENV_IN_CODE = re.compile(r'os\.environ(?:\.get)?\(?\[?\s*["\']([A-Z][A-Z0-9_]*)["\']')
_ENV_IN_EXAMPLE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", re.M)


def _unescape(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&hellip;", "…")
        .replace("&nbsp;", " ")
    )


def _code_fragments(root: Path) -> list[tuple[Path, int, str]]:
    """Every <code> body in docs/**/*.html as (file, 1-based line, text)."""
    out: list[tuple[Path, int, str]] = []
    for html in sorted((root / "docs").rglob("*.html")):
        text = html.read_text(encoding="utf-8", errors="replace")
        for match in _CODE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            # Nested markup (a <span> highlight inside <code>) is stripped: the
            # fragment is read as the path or name a human sees, not as HTML.
            body = _unescape(_TAG.sub("", match.group(1))).strip()
            if body:
                out.append((html.relative_to(root), line, body))
    return out


def _candidate_paths(fragment: str) -> list[str]:
    """Every repo path a fragment names.

    A code fragment is often a command (`bash scripts/tests/run.sh quick`), a
    path with a placeholder (`apps/<dienst>/tests/…`), or a whole directory tree
    spanning many lines — the docs carry 100 multi-line <code> bodies, and those
    age fastest of all. So every token is considered, not just the first; a token
    carrying a placeholder is not a path anyone could resolve and is skipped.
    """
    out: list[str] = []
    for token in fragment.replace("\n", " ").split(" "):
        token = token.strip().strip(",;:()`\"'")
        if not token.startswith(_PATH_PREFIXES):
            continue
        token = re.split(r"[\[\{]", token, maxsplit=1)[0]
        if any(ch in token for ch in "<>*|$"):
            continue
        cleaned = token.rstrip(".")
        if cleaned:
            out.append(cleaned)
    return out


def _tracked_paths(root: Path) -> set[str] | None:
    """Every tracked file plus its parent directories, or None outside a repo.

    Existence is resolved against what git tracks, not against the working tree:
    `apps/web/dist/` and `apps/desktop/src-tauri/binaries/` exist on a developer
    box and never in a fresh checkout, so a filesystem check passes locally and
    fails on the runner — the one failure mode a documentation gate must not have.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    known: set[str] = set()
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        known.add(rel)
        parent = Path(rel).parent
        while str(parent) != ".":
            known.add(str(parent))
            known.add(str(parent) + "/")
            parent = parent.parent
    return known


def _known_env_names(root: Path) -> set[str]:
    names: set[str] = set()
    for rel in _CONFIGS:
        path = root / rel
        if path.exists():
            names.update(_ENV_IN_CODE.findall(path.read_text(encoding="utf-8")))
    example = root / ".env.example"
    if example.exists():
        names.update(_ENV_IN_EXAMPLE.findall(example.read_text(encoding="utf-8")))
    return names


def _load_allowlist(root: Path) -> set[str] | None:
    path = root / "scripts" / "dev" / "doc-smoke-allow.txt"
    if not path.exists():
        return set()
    entries: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.split("#", 1)[0].strip()
        if entry:
            entries.add(entry)
    if len(entries) > _ALLOW_MAX:
        print(
            f"doc-smoke: {path.relative_to(root)} has {len(entries)} entries, "
            f"the cap is {_ALLOW_MAX} — fix the documentation instead",
            file=sys.stderr,
        )
        return None
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description="documentation smoke test")
    parser.add_argument("--paths", action="store_true", help="check repo paths (default)")
    parser.add_argument("--env", action="store_true", help="check environment-variable names")
    parser.add_argument("--strict", action="store_true", help="findings make the run fail")
    parser.add_argument("--root", default=None, help="operate on another checkout")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent.parent
    if not (root / "docs").is_dir():
        print(f"doc-smoke: no docs/ under {root}", file=sys.stderr)
        return 2

    check_paths = args.paths or not args.env
    allow = _load_allowlist(root)
    if allow is None:
        return 2
    fragments = _code_fragments(root)
    findings: list[str] = []

    if check_paths:
        tracked = _tracked_paths(root)
        if tracked is None:
            print(
                "doc-smoke: not a git checkout — falling back to the working tree", file=sys.stderr
            )

        def _exists(candidate: str) -> bool:
            if tracked is None:
                return (root / candidate).exists()
            return candidate in tracked or candidate.rstrip("/") in tracked

        collected: set[str] = set()
        for rel, line, fragment in fragments:
            for candidate in _candidate_paths(fragment):
                collected.add(candidate)
                if candidate in allow:
                    continue
                if not _exists(candidate):
                    findings.append(f"{rel}:{line}: {candidate}")
        # A collector that reads nothing would report a clean documentation set
        # for an empty docs/ tree — the failure mode this whole stage is about.
        # Counted over DISTINCT paths and set near the real number, so a parser
        # that quietly loses most of its coverage is caught too, not just a total
        # outage.
        if len(collected) < _PATH_FLOOR:
            print(
                f"doc-smoke: only {len(collected)} distinct repo paths collected, floor is "
                f"{_PATH_FLOOR} — either the scan broke or the documentation genuinely "
                f"shrank. Check which before lowering the floor.",
                file=sys.stderr,
            )
            return 2

    if args.env:
        known = _known_env_names(root)
        if len(known) < 10:
            print(f"doc-smoke: only {len(known)} env names read from the sources", file=sys.stderr)
            return 2
        for rel, line, fragment in fragments:
            name = fragment.strip()
            if not _ENV_NAME.match(name) or name in known or name in allow:
                continue
            findings.append(f"{rel}:{line}: {name}")

    for finding in sorted(set(findings)):
        print(finding)
    if findings:
        print(f"doc-smoke: {len(set(findings))} finding(s)", file=sys.stderr)
        return 1 if args.strict else 0
    print("doc-smoke: documentation matches the tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
