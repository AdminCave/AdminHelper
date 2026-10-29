#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""changelog-assemble.py — fold changelog.d/ into the [Unreleased] section of CHANGELOG.md.

    python3 scripts/release/changelog-assemble.py [--check] [--root <dir>]

Every branch writes its entries into its own changelog.d/<slug>.md instead of
CHANGELOG.md: parallel branches then never touch the same file (GitHub ignores
the union merge, .claude/rules/docs.md). A fragment holds Keep a Changelog
subsections only (`### Added` … `### Security`) with their entries below.

The release (.claude/rules/release.md) runs this before it renames
[Unreleased]: each fragment's entries go to the end of the subsection of the
same name in [Unreleased] (a missing subsection is added at the end of the
section), in the order of the file names; everything else in CHANGELOG.md stays
byte for byte; the fragments are deleted. --check only reads them.

Exit: 0 ok (or nothing to fold) · 1 a fragment does not fit the format · 2 usage
"""

from __future__ import annotations

import argparse
import pathlib
import sys

HEADINGS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")


class FormatError(Exception):
    pass


def parse_fragment(name: str, text: str) -> list[tuple[str, list[str]]]:
    """The subsections of a fragment, each with its lines (outer blank lines dropped)."""
    out: list[tuple[str, list[str]]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("#"):
            head = line[4:].strip() if line.startswith("### ") else ""
            if head not in HEADINGS:
                raise FormatError(f"{name}:{n}: '{line}' is not one of ### {' / '.join(HEADINGS)}")
            out.append((head, []))
        elif line.strip() and not out:
            raise FormatError(f"{name}:{n}: text before the first ### heading")
        elif out:
            out[-1][1].append(line)
    for head, lines in out:
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            raise FormatError(f"{name}: ### {head} has no entry")
    if not out:
        raise FormatError(f"{name}: no ### heading")
    return out


def fold(changelog: str, fragments: list[tuple[str, list[tuple[str, list[str]]]]]) -> str:
    lines = changelog.split("\n")
    try:
        start = lines.index("## [Unreleased]")
    except ValueError:
        raise FormatError("CHANGELOG.md: no '## [Unreleased]' section") from None
    for _, parts in fragments:
        for head, entries in parts:
            end = next(
                (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
            )
            at = next((i for i in range(start + 1, end) if lines[i] == f"### {head}"), None)
            if at is None:
                # A new subsection at the end of [Unreleased], before its blank tail.
                ins = end
                while ins > start + 1 and not lines[ins - 1].strip():
                    ins -= 1
                lines[ins:ins] = ["", f"### {head}", "", *entries]
                continue
            stop = next((i for i in range(at + 1, end) if lines[i].startswith("### ")), end)
            last = stop
            while last > at + 1 and not lines[last - 1].strip():
                last -= 1
            lines[last:last] = entries
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true", help="only read and check the fragments")
    p.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[2]))
    args = p.parse_args(argv)
    root = pathlib.Path(args.root)
    files = sorted(f for f in (root / "changelog.d").glob("*.md") if f.name != "README.md")
    try:
        for f in files:
            if f.is_symlink():
                raise FormatError(f"{f.name}: a symlink, not a fragment")
        fragments = [(f.name, parse_fragment(f.name, f.read_text(encoding="utf-8"))) for f in files]
        if args.check or not fragments:
            print(f"changelog-assemble: {len(fragments)} fragment(s) ok")
            return 0
        target = root / "CHANGELOG.md"
        target.write_text(fold(target.read_text(encoding="utf-8"), fragments), encoding="utf-8")
    except FormatError as e:
        print(f"changelog-assemble: {e}", file=sys.stderr)
        return 1
    for f in files:
        f.unlink()
    print(
        f"changelog-assemble: {len(files)} fragment(s) folded into [Unreleased]: {' '.join(f.name for f in files)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
