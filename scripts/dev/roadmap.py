#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""roadmap.py — the roadmap as a script: tasks/private/ROADMAP.md, read and linted.

    python3 scripts/dev/roadmap.py [--file <path>] [--today YYYY-MM-DD] lint

The file stays Markdown that Kevin edits by hand. The script understands the
header line and the ten-column table rows (ID | Klasse | Titel | Status |
Quelle / Beweis | Ledger | Hängt ab von | PR | Ablauf | Kevin-min); everything
else — prose, "Als Nächstes", blank lines, a row it cannot read — passes
through byte for byte (spec: docs/features/harness-stufe-5.md).

The file is --file, else $AH_ROADMAP, else tasks/private/ROADMAP.md. Tests
always name a fixture: the real file is Kevin's. --today pins the date that
expiry (ALT) is computed against, so a test does not depend on the calendar.

lint reports, one line per finding with the row's ID and line: duplicate IDs,
unknown statuses (the aliases `geparkt` and `erledigt` by name), rows in the
section their status does not belong in, rows without exactly ten columns, a
Dedup-Key two open rows share, and a WIP header the rows do not add up to.

Exit codes: 0 clean · 1 findings · 2 usage (no such file, bad arguments).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_FILE = ROOT / "tasks" / "private" / "ROADMAP.md"

NCOLS = 10
ID, KLASSE, TITEL, STATUS, QUELLE, LEDGER, DEPENDS, PR, ABLAUF, KEVIN_MIN = range(NCOLS)

SECTIONS = (
    "Als Nächstes",
    "In Arbeit",
    "Neu",
    "Geplant",
    "Zurückgestellt",
    "Blockiert",
    "Abgeschlossen",
    "Archiv",
)
# Where a row with this status belongs. A closed row may also sit in the
# archive: it moves there by age, not by status.
SECTION_OF = {
    "neu": "Neu",
    "geplant": "Geplant",
    "freigegeben": "Geplant",
    "aktiv": "In Arbeit",
    "bereit": "In Arbeit",
    "pr": "In Arbeit",
    "zurückgestellt": "Zurückgestellt",
    "blockiert": "Blockiert",
    "abgeschlossen": "Abgeschlossen",
    "abgelehnt": "Abgeschlossen",
}
CLOSED = frozenset({"abgeschlossen", "abgelehnt"})
ALIASES = {"geparkt": "zurückgestellt", "erledigt": "abgeschlossen"}
# The header's counters, in the order it prints them; the caps are CLAUDE.md's.
WIP_CAPS = (("aktiv", 1), ("bereit", 2), ("pr", 3), ("neu", 20))

# A cell may carry a pipe only escaped (`\|`); an unescaped one starts a new
# cell, which is exactly how a row ends up with eleven columns.
CELL_SPLIT = re.compile(r"(?<!\\)\|")
SEPARATOR = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$")
ROW_ID = re.compile(r"R-\d{4,}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DEDUP = re.compile(r"Dedup-Key:\s*(\S+)")
WIP_FIELD = re.compile(r"\b(aktiv|bereit|pr|neu)\s+(\d+)\s*/\s*\d+")
ALT_FIELD = re.compile(r"\bALT:\s*(\d+)")


class UsageError(Exception):
    """Exit 2: the call itself is wrong, or the file is not there."""


@dataclass
class Row:
    """One table row. `raw` is the line as read; a row nobody changed is
    written back from it, so reading never reformats Kevin's file."""

    cells: list[str]
    raw: str | None = None
    lineno: int = 0

    @property
    def id(self) -> str:
        return self.cells[ID] if self.cells else ""

    @property
    def well_formed(self) -> bool:
        return len(self.cells) == NCOLS

    @property
    def status(self) -> str:
        """The status word; what follows it in the column is a note."""
        words = self.cells[STATUS].split() if len(self.cells) > STATUS else []
        return words[0] if words else ""

    @property
    def state(self) -> str:
        """The status with an alias resolved."""
        return ALIASES.get(self.status, self.status)

    @property
    def is_open(self) -> bool:
        return self.state in SECTION_OF and self.state not in CLOSED

    def text(self) -> str:
        if self.raw is not None:
            return self.raw
        return "| " + " | ".join(self.cells) + " |"


def split_cells(line: str) -> list[str]:
    parts = CELL_SPLIT.split(line)
    # "| a | b |" -> ["", " a ", " b ", ""]: the outer pipes frame the row.
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip() for p in parts]


def parse_day(cell: str) -> dt.date | None:
    """The first YYYY-MM-DD in a cell; None when there is none or it is no date."""
    m = DATE.search(cell)
    try:
        return dt.date.fromisoformat(m.group(0)) if m else None
    except ValueError:
        return None


def section_name(heading: str) -> str:
    title = heading[3:].strip()
    for name in SECTIONS:
        if title == name or title.startswith(name + " "):
            return name
    return title


class Roadmap:
    """The file as a list of items: a Row where a table row stood, the line
    itself everywhere else."""

    def __init__(self, text: str) -> None:
        self.ends_with_newline = text.endswith("\n")
        lines = text.split("\n")
        if self.ends_with_newline:
            lines = lines[:-1]
        self.items: list[str | Row] = []
        in_section = False
        for n, line in enumerate(lines, 1):
            if line.startswith("## "):
                in_section = True
            # Every `|` line under a heading is a row: one the parser cannot
            # read becomes a lint finding, never a line silently left out.
            elif in_section and line.startswith("|") and not SEPARATOR.match(line):
                cells = split_cells(line)
                if cells and cells[0] != "ID":  # "ID" heads the column row
                    self.items.append(Row(cells, line, n))
                    continue
            self.items.append(line)

    @classmethod
    def load(cls, path: pathlib.Path) -> Roadmap:
        try:
            return cls(path.read_bytes().decode("utf-8"))
        except FileNotFoundError:
            raise UsageError(f"no such file: {path}") from None

    def render(self) -> str:
        body = "\n".join(i.text() if isinstance(i, Row) else i for i in self.items)
        return body + ("\n" if self.ends_with_newline else "")

    def rows(self) -> list[tuple[str, Row]]:
        """(section, row) in file order. Rows exist only under a heading."""
        out: list[tuple[str, Row]] = []
        section = ""
        for item in self.items:
            if isinstance(item, Row):
                out.append((section, item))
            elif item.startswith("## "):
                section = section_name(item)
        return out

    def header_index(self) -> int | None:
        """The `Stand: … · WIP: …` line above the first section."""
        for i, item in enumerate(self.items):
            if isinstance(item, str):
                if item.startswith("## "):
                    return None
                if item.startswith("Stand:"):
                    return i
        return None

    def counts(self, today: dt.date) -> dict[str, int]:
        """What the header should say: open rows per WIP state, and ALT, the
        open rows whose Ablauf date has passed."""
        counts = {state: 0 for state, _ in WIP_CAPS}
        counts["ALT"] = 0
        for _, row in self.rows():
            if not row.well_formed or not row.is_open:
                continue
            if row.state in counts:
                counts[row.state] += 1
            expiry = parse_day(row.cells[ABLAUF])
            if expiry and expiry < today:
                counts["ALT"] += 1
        return counts


@dataclass
class Finding:
    lineno: int
    who: str
    reason: str

    def __str__(self) -> str:
        return f"{self.who} line {self.lineno}: {self.reason}"


def lint(roadmap: Roadmap, today: dt.date) -> list[Finding]:
    found: list[Finding] = []
    first_line: dict[str, int] = {}
    dedup_owner: dict[str, str] = {}
    for section, row in roadmap.rows():
        has_id = ROW_ID.fullmatch(row.id) is not None
        who = row.id if has_id else "row"
        # Before the column check: a row with a stray | still holds its ID.
        if has_id and row.id in first_line:
            found.append(
                Finding(row.lineno, who, f"duplicate ID (first at line {first_line[row.id]})")
            )
        elif has_id:
            first_line[row.id] = row.lineno
        if not row.well_formed:
            found.append(Finding(row.lineno, who, f"{len(row.cells)} columns, expected {NCOLS}"))
            continue
        status = row.status
        if status in ALIASES:
            found.append(
                Finding(
                    row.lineno, who, f"status '{status}' is an alias, write '{ALIASES[status]}'"
                )
            )
        elif status not in SECTION_OF:
            found.append(Finding(row.lineno, who, f"unknown status '{status}'"))
        else:
            home = SECTION_OF[status]
            allowed = {home, "Archiv"} if status in CLOSED else {home}
            if section not in allowed:
                where = section or "no section"
                found.append(
                    Finding(
                        row.lineno, who, f"status '{status}' belongs in '{home}', not '{where}'"
                    )
                )
        key = DEDUP.search(row.cells[QUELLE])
        if key and row.is_open:
            if key.group(1) in dedup_owner:
                owner = dedup_owner[key.group(1)]
                found.append(
                    Finding(row.lineno, who, f"Dedup-Key '{key.group(1)}' is already on {owner}")
                )
            else:
                dedup_owner[key.group(1)] = row.id
    found.extend(lint_header(roadmap, today))
    return sorted(found, key=lambda f: f.lineno)


def lint_header(roadmap: Roadmap, today: dt.date) -> list[Finding]:
    i = roadmap.header_index()
    line = roadmap.items[i] if i is not None else ""
    lineno = (i or 0) + 1
    if not isinstance(line, str) or "WIP:" not in line:
        return [Finding(lineno, "header", "no 'Stand: … · WIP: …' line above the first section")]
    said = {k: int(v) for k, v in WIP_FIELD.findall(line)}
    alt = ALT_FIELD.search(line)
    if alt:
        said["ALT"] = int(alt.group(1))
    found = []
    for key, value in roadmap.counts(today).items():
        if key not in said:
            found.append(Finding(lineno, "header", f"WIP has no '{key}' (the rows say {value})"))
        elif said[key] != value:
            found.append(
                Finding(lineno, "header", f"WIP says {key} {said[key]}, the rows say {value}")
            )
    return found


def roadmap_path(given: str | None) -> pathlib.Path:
    return pathlib.Path(given or os.environ.get("AH_ROADMAP") or DEFAULT_FILE)


def cmd_lint(args: argparse.Namespace) -> int:
    path = roadmap_path(args.file)
    found = lint(Roadmap.load(path), args.today)
    for f in found:
        print(f)
    if found:
        print(f"lint: {path}: {len(found)} finding(s)", file=sys.stderr)
        return 1
    print(f"lint: {path} ok")
    return 0


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {value}") from None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="roadmap.py", description="The roadmap as a script.")
    p.add_argument(
        "--file", help="the roadmap (default: $AH_ROADMAP, else tasks/private/ROADMAP.md)"
    )
    p.add_argument(
        "--today",
        type=parse_date,
        default=dt.date.today(),
        help="the date expiry is computed against (default: today; for tests)",
    )
    sub = p.add_subparsers(dest="verb", required=True)
    sub.add_parser("lint", help="report what does not fit the format").set_defaults(func=cmd_lint)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as e:
        print(f"roadmap.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
