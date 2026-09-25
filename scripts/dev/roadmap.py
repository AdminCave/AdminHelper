#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""roadmap.py — the roadmap as a script: tasks/private/ROADMAP.md, read, linted, written.

    python3 scripts/dev/roadmap.py [--file <path>] [--today YYYY-MM-DD] <verb>

    lint                        what does not fit the format
    add --class K --title T --source S [--proof P] [--dedup-key K] [--ledger L]
                                a `neu` row at the end of "Neu"; prints its ID
    status <id> <status> [--note N]
                                set the status; the row moves to its section
    approve <id> [--revoke]     geplant -> freigegeben, or back

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

Every write runs under flock on <file>.lock, saves <file>.bak first, checks
that the row count moved by exactly what the verb meant (else the .bak goes
back), rewrites the header (`Stand: <today> · WIP: …`), and commits the file
alone in its own repository — locally, never pushed, and never in this public
one. A file changed in the last 5 s by anyone but roadmap.py (the mtime
differs from the one the lock file remembers) is refused: an editor may hold
it. The ID is the highest R-nnnn of all rows plus one. A closed row
(abgeschlossen, abgelehnt) carries the day it closed; more than 30 days later
the next write moves it from "Abgeschlossen" to the top of "Archiv".

A status follows only from the ones TRANSITIONS names (exit 2 otherwise).
Setting a row's own status again is always allowed: it files a row left in
the wrong section into its own, and turns an alias into the real word.

Exit codes: 0 ok · 1 lint findings · 2 usage (no such file, bad arguments) ·
3 the `neu` cap (20) is reached · 4 an open row already carries the Dedup-Key ·
5 the file was just changed by hand · 6 the row count came out wrong (restored).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_FILE = ROOT / "tasks" / "private" / "ROADMAP.md"

NCOLS = 10
ID, KLASSE, TITEL, STATUS, QUELLE, LEDGER, DEPENDS, PR, ABLAUF, KEVIN_MIN = range(NCOLS)
COLUMNS = (
    "ID",
    "Klasse",
    "Titel",
    "Status",
    "Quelle / Beweis",
    "Ledger",
    "Hängt ab von",
    "PR",
    "Ablauf",
    "Kevin-min",
)
TABLE_HEAD = "| " + " | ".join(COLUMNS) + " |"
TABLE_SEP = "|" + "---|" * NCOLS
CLASSES = ("SEC", "REG", "REL", "BUG", "FEAT", "REF", "IDEE")
# Ablauf of a new row (roadmap document 3.3.2); every other class never expires.
EXPIRY_DAYS = {"IDEE": 60, "REF": 90}
QUIET_SECONDS = 5
ARCHIVE_AFTER_DAYS = 30

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
NEU_CAP = dict(WIP_CAPS)["neu"]
# Which status may follow which (the Ledger chain of the spec, plus the ways
# out: zurückgestellt, blockiert, abgelehnt). A closed row only turns
# abgelehnt — a throwaway row that must not count as done.
TRANSITIONS = {
    "neu": {"geplant", "zurückgestellt", "blockiert", "abgelehnt"},
    "geplant": {"freigegeben", "aktiv", "zurückgestellt", "blockiert", "abgelehnt"},
    "freigegeben": {"geplant", "aktiv", "zurückgestellt", "blockiert", "abgelehnt"},
    "aktiv": {"bereit", "geplant", "zurückgestellt", "blockiert", "abgelehnt"},
    "bereit": {"pr", "aktiv", "zurückgestellt", "blockiert", "abgelehnt"},
    "pr": {"abgeschlossen", "aktiv", "zurückgestellt", "blockiert", "abgelehnt"},
    "zurückgestellt": {"neu", "geplant", "abgelehnt"},
    "blockiert": {"geplant", "freigegeben", "aktiv", "zurückgestellt", "abgelehnt"},
    "abgeschlossen": {"abgelehnt"},
    "abgelehnt": set(),
}

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


class Refused(Exception):
    """A write that must not happen; `code` is the exit code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


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

    @property
    def dedup_key(self) -> str | None:
        m = DEDUP.search(self.cells[QUELLE]) if self.well_formed else None
        return m.group(1) if m else None

    def text(self) -> str:
        if self.raw is not None:
            return self.raw
        return "| " + " | ".join(self.cells) + " |"


def cell(value: str) -> str:
    """A value for a new cell: one line, its pipes escaped, never empty."""
    value = " ".join(value.split())
    return CELL_SPLIT.sub(r"\\|", value) or "—"


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

    def section_bounds(self, name: str) -> tuple[int, int]:
        """Item indices [heading, next heading) of the section `name`."""
        start = None
        for i, item in enumerate(self.items):
            if isinstance(item, str) and item.startswith("## "):
                if start is not None:
                    return start, i
                if section_name(item) == name:
                    start = i
        if start is None:
            raise UsageError(f"the roadmap has no '## {name}' section")
        return start, len(self.items)

    def insert_row(self, section: str, row: Row, top: bool = False) -> None:
        """At the end of the section's table (or its top); a section without
        a table gets one right under its heading."""
        start, end = self.section_bounds(section)
        rows = [i for i in range(start, end) if isinstance(self.items[i], Row)]
        seps = [
            i
            for i in range(start, end)
            if isinstance(self.items[i], str) and SEPARATOR.match(self.items[i])
        ]
        if rows:
            at = rows[0] if top else rows[-1] + 1
        elif seps:
            at = seps[0] + 1
        else:
            self.items[start + 1 : start + 1] = [TABLE_HEAD, TABLE_SEP]
            at = start + 3
        self.items.insert(at, row)

    def remove(self, row: Row) -> None:
        """By identity: two rows may look alike (the duplicate IDs lint reports)."""
        del self.items[next(i for i, item in enumerate(self.items) if item is row)]

    def find(self, rid: str) -> tuple[str, Row]:
        """The one well-formed row with this ID, and its section."""
        hits = [(s, r) for s, r in self.rows() if r.id == rid]
        if not hits:
            raise UsageError(f"no row {rid}")
        if len(hits) > 1:
            raise UsageError(f"{rid} is on {len(hits)} rows — fix the IDs by hand first (lint)")
        section, row = hits[0]
        if not row.well_formed:
            raise UsageError(f"{rid} has {len(row.cells)} columns — fix the row by hand first")
        return section, row

    def set_status(self, rid: str, new: str, note: str | None, today: dt.date) -> None:
        section, row = self.find(rid)
        old = row.state
        if old not in TRANSITIONS:
            raise UsageError(f"{rid} has the unknown status '{row.status}' — fix it by hand")
        if new != old and new not in TRANSITIONS[old]:
            allowed = ", ".join(sorted(TRANSITIONS[old])) or "nothing"
            raise UsageError(f"{rid}: {old} -> {new} is no transition (from {old}: {allowed})")
        if new != old or note is not None:
            # A closed row keeps the day it closed when only its note changes.
            kept = parse_day(row.cells[STATUS]) if new == old else None
            day = f" {(kept or today).isoformat()}" if new in CLOSED else ""
            row.cells[STATUS] = cell(new + day + (f" ({note})" if note else ""))
            row.raw = None
        elif row.status != new:
            # An alias turns into the word; its day and note stay.
            row.cells[STATUS] = new + row.cells[STATUS][len(row.status) :]
            row.raw = None
        home = SECTION_OF[new]
        # A closed row that only confirms its status may stay in the archive.
        filed = section == home or (new == old and new in CLOSED and section == "Archiv")
        if not filed:
            self.remove(row)
            self.insert_row(home, row, top=home == "Abgeschlossen")

    def archive(self, today: dt.date) -> None:
        """Closed rows more than ARCHIVE_AFTER_DAYS past their date leave
        "Abgeschlossen" for the top of "Archiv", in the order they stood."""
        old = []
        for section, row in self.rows():
            day = parse_day(row.cells[STATUS]) if row.well_formed else None
            if section == "Abgeschlossen" and row.state in CLOSED and day:
                if (today - day).days > ARCHIVE_AFTER_DAYS:
                    old.append(row)
        for row in reversed(old):
            self.remove(row)
            self.insert_row("Archiv", row, top=True)

    def next_id(self) -> str:
        nums = [int(r.id[2:]) for _, r in self.rows() if ROW_ID.fullmatch(r.id)]
        return f"R-{max(nums, default=0) + 1:04d}"

    def set_header(self, today: dt.date) -> None:
        """`Stand: <today> · WIP: …` computed from the rows, above the first section."""
        c = self.counts(today)
        wip = " · ".join(f"{state} {c[state]}/{cap}" for state, cap in WIP_CAPS)
        line = f"Stand: {today.isoformat()} · WIP: {wip} · ALT: {c['ALT']}"
        i = self.header_index()
        if i is not None:
            self.items[i] = line
            return
        first = self.items[0] if self.items else ""
        at = 1 if isinstance(first, str) and first.startswith("# ") else 0
        self.items.insert(at, line)

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


def sibling(path: pathlib.Path, suffix: str) -> pathlib.Path:
    return path.with_name(path.name + suffix)


def replace_file(path: pathlib.Path, data: bytes) -> None:
    """Atomically: a reader sees the old file or the new one, never half."""
    tmp = sibling(path, ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_text(path: pathlib.Path, text: str) -> None:
    """The one place a new roadmap reaches the disk."""
    replace_file(path, text.encode("utf-8"))


def mark(path: pathlib.Path, data: bytes) -> str:
    """What roadmap.py's own last write looked like: mtime and content. The
    mtime alone is not enough — it moves in clock ticks of a few ms, and a hand
    edit inside the same tick would pass for our own."""
    return f"{path.stat().st_mtime_ns} {hashlib.sha256(data).hexdigest()}"


def remember(lock, path: pathlib.Path) -> None:
    """The lock file keeps the mark of roadmap.py's own last write."""
    lock.seek(0)
    lock.truncate()
    lock.write(mark(path, path.read_bytes()))
    lock.flush()


def write(
    path: pathlib.Path,
    change: Callable[[Roadmap], str],
    *,
    verb: str,
    delta: int,
    detail: str = "",
    today: dt.date,
    clock: Callable[[], float] = time.time,
) -> str:
    """Apply `change` (it returns the row's ID) under the lock; `delta` is
    how many rows the change adds."""
    with open(sibling(path, ".lock"), "a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise UsageError(f"no such file: {path}") from None
        lock.seek(0)
        age = clock() - path.stat().st_mtime
        if lock.read().strip() != mark(path, data) and age < QUIET_SECONDS:
            raise Refused(
                5,
                f"{path} was changed {age:.1f} s ago, not by roadmap.py — an editor may "
                f"still hold it; try again in {QUIET_SECONDS} s",
            )
        before_text = data.decode("utf-8")
        roadmap = Roadmap(before_text)
        before = len(roadmap.rows())
        rid = change(roadmap)
        roadmap.archive(today)
        roadmap.set_header(today)
        bak = sibling(path, ".bak")
        bak.write_bytes(before_text.encode("utf-8"))
        write_text(path, roadmap.render())
        after = len(Roadmap(path.read_bytes().decode("utf-8")).rows())
        if after != before + delta:
            replace_file(path, bak.read_bytes())
            remember(lock, path)
            raise Refused(
                6,
                f"{before} rows {delta:+d} should make {before + delta}, the written file "
                f"has {after} — restored from {bak}",
            )
        remember(lock, path)
        commit(path, f"roadmap: {verb} {rid}{detail}")
    return rid


def commit(path: pathlib.Path, message: str) -> None:
    """Commit this one file in the repository it lives in. Locally: pushing
    the private repo is Kevin's. Never in this public repository."""

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], capture_output=True, text=True)

    top = git("-C", str(path.parent), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        print(f"roadmap.py: {path.parent} is no git repository — not committed", file=sys.stderr)
        return
    repo = pathlib.Path(top.stdout.strip()).resolve()
    if repo == ROOT.resolve():
        print(f"roadmap.py: {path} is in the public repository — not committed", file=sys.stderr)
        return
    rel = str(path.resolve().relative_to(repo))
    for args in (("add", "--", rel), ("commit", "-q", "-m", message, "--", rel)):
        r = git("-C", str(repo), *args)
        if r.returncode != 0:
            print(
                f"roadmap.py: git {args[0]} failed, written but not committed: {r.stderr.strip()}",
                file=sys.stderr,
            )
            return


def cmd_status(args: argparse.Namespace) -> int:
    def change(roadmap: Roadmap) -> str:
        roadmap.set_status(args.id, args.value, args.note, args.today)
        return args.id

    path = roadmap_path(args.file)
    write(path, change, verb="status", delta=0, detail=f" {args.value}", today=args.today)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    was, new = ("freigegeben", "geplant") if args.revoke else ("geplant", "freigegeben")

    def change(roadmap: Roadmap) -> str:
        _, row = roadmap.find(args.id)
        if row.state != was:
            raise UsageError(f"{args.id} is {row.status or 'without status'}, not {was}")
        roadmap.set_status(args.id, new, None, args.today)
        return args.id

    detail = " --revoke" if args.revoke else ""
    write(roadmap_path(args.file), change, verb="approve", delta=0, detail=detail, today=args.today)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    if not args.title.strip() or not args.source.strip():
        raise UsageError("a row needs a --title and a --source")
    if args.dedup_key is not None and (not args.dedup_key or len(args.dedup_key.split()) != 1):
        raise UsageError(f"a Dedup-Key is one token: {args.dedup_key!r}")

    def change(roadmap: Roadmap) -> str:
        rows = [r for _, r in roadmap.rows() if r.well_formed]
        neu = sum(r.state == "neu" for r in rows)
        if neu >= NEU_CAP:
            raise Refused(3, f"the neu cap is reached ({neu}/{NEU_CAP}) — triage first")
        if args.dedup_key:
            owner = next((r.id for r in rows if r.is_open and r.dedup_key == args.dedup_key), None)
            if owner:
                raise Refused(4, f"Dedup-Key {args.dedup_key} is already on open row {owner}")
        rid = roadmap.next_id()
        key = f"Dedup-Key: {args.dedup_key}" if args.dedup_key else ""
        source = " · ".join(v for v in (args.source, args.proof or "", key) if v)
        days = EXPIRY_DAYS.get(args.klass)
        ablauf = (args.today + dt.timedelta(days=days)).isoformat() if days else "nie"
        cells = [rid, args.klass, cell(args.title), "neu", cell(source)]
        cells += [cell(args.ledger or ""), "—", "—", ablauf, "—"]
        roadmap.insert_row("Neu", Row(cells))
        return rid

    print(write(roadmap_path(args.file), change, verb="add", delta=1, today=args.today))
    return 0


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
    a = sub.add_parser("add", help="append a `neu` row and print its ID")
    a.add_argument("--class", dest="klass", required=True, choices=CLASSES)
    a.add_argument("--title", required=True)
    a.add_argument("--source", required=True, help="where it comes from, e.g. 'weekly 2026-09-25'")
    a.add_argument("--proof", help="where the proof lives, e.g. Branch@SHA")
    a.add_argument("--dedup-key", help="<klasse>:<komponente>:<datei>:<symbol>, one token")
    a.add_argument("--ledger", help="the ledger, if there is one")
    a.set_defaults(func=cmd_add)
    st = sub.add_parser("status", help="set a row's status; the row moves to its section")
    st.add_argument("id")
    st.add_argument("value", choices=sorted(SECTION_OF), metavar="status")
    st.add_argument("--note", help="appended in parentheses, e.g. 'PR #42'")
    st.set_defaults(func=cmd_status)
    ap = sub.add_parser("approve", help="geplant -> freigegeben (Kevin's approval)")
    ap.add_argument("id")
    ap.add_argument("--revoke", action="store_true", help="freigegeben -> geplant")
    ap.set_defaults(func=cmd_approve)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except UsageError as e:
        print(f"roadmap.py: {e}", file=sys.stderr)
        return 2
    except Refused as e:
        print(f"roadmap.py: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
