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
    show [<id>] [--wip]         one row, the WIP counters, or the overview
    next [--status S] [--exclude-components C …]
                                the next row to build; exit 1 when there is none
    sync                        rows whose PRs are all merged (gh) -> abgeschlossen
    stats [--days N]            tasks/day, Kevin-min/PR, wait per state, stale, dedup

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

next picks by class (SEC > REG > REL > BUG > FEAT > REF > IDEE), then by the
order of the rows (Kevin's), and skips a row whose "Hängt ab von" names an
R-ID that is not abgeschlossen, or that touches an excluded component (the
`Komponente:` lines of its ledger, the second field of its Dedup-Key). sync
prints the push of the private repository; it never runs it.

A status follows only from the ones TRANSITIONS names (exit 2 otherwise).
Setting a row's own status again is always allowed: it files a row left in
the wrong section into its own, and turns an alias into the real word.

Exit codes: 0 ok · 1 lint findings · 2 usage (no such file, bad arguments) ·
3 the `neu` cap (20) is reached · 4 an open row already carries the Dedup-Key
(recorded as an empty commit `roadmap: dedup <key> -> R-nnnn`, for stats) ·
5 the file was just changed by hand · 6 the row count came out wrong (restored) ·
74 gh could not list the merged PRs (sync). next: 1 when no row is ready.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from collections import defaultdict
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
CLASS_RANK = {k: i for i, k in enumerate(CLASSES)}
# The order `stats` prints the waits in: the chain first, the ways out after.
STATE_ORDER = (
    "neu",
    "geplant",
    "freigegeben",
    "aktiv",
    "bereit",
    "pr",
    "zurückgestellt",
    "blockiert",
)
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


class NothingToClose(Exception):
    """sync: no open row names only merged PRs (any more)."""


class Duplicate(Refused):
    """Exit 4: an open row already carries the Dedup-Key."""

    def __init__(self, key: str, owner: str) -> None:
        super().__init__(4, f"Dedup-Key {key} is already on open row {owner}")
        self.key, self.owner = key, owner


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

    def set_status(
        self, rid: str, new: str, note: str | None, today: dt.date, check: bool = True
    ) -> None:
        """`check=False` is sync's: a merged PR closes a row from any status."""
        section, row = self.find(rid)
        old = row.state
        if old not in TRANSITIONS:
            raise UsageError(f"{rid} has the unknown status '{row.status}' — fix it by hand")
        if check and new != old and new not in TRANSITIONS[old]:
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
        line = f"Stand: {today.isoformat()} · {wip_text(self.counts(today))}"
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


def wip_text(counts: dict[str, int]) -> str:
    wip = " · ".join(f"{state} {counts[state]}/{cap}" for state, cap in WIP_CAPS)
    return f"WIP: {wip} · ALT: {counts['ALT']}"


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


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def git_out(repo: pathlib.Path, *args: str) -> str:
    r = git("-C", str(repo), *args)
    return r.stdout if r.returncode == 0 else ""


def repo_of(path: pathlib.Path) -> pathlib.Path | None:
    r = git("-C", str(path.parent), "rev-parse", "--show-toplevel")
    return pathlib.Path(r.stdout.strip()).resolve() if r.returncode == 0 else None


def private_repo(path: pathlib.Path) -> pathlib.Path | None:
    """The repository roadmap.py may commit in: the file's own, locally
    (pushing the private repo is Kevin's), and never this public one."""
    repo = repo_of(path)
    if repo is None:
        print(f"roadmap.py: {path.parent} is no git repository — not committed", file=sys.stderr)
    elif repo == ROOT.resolve():
        print(f"roadmap.py: {path} is in the public repository — not committed", file=sys.stderr)
        return None
    return repo


def commit_empty(path: pathlib.Path, message: str) -> None:
    """A commit on HEAD's own tree, by plumbing: `git commit --allow-empty`
    would sweep in whatever is staged, and a path limit would take along a
    hand edit of the file."""
    repo = private_repo(path)
    if repo is None:
        return
    head = git_out(repo, "rev-parse", "--verify", "HEAD").strip()
    new = git_out(repo, "commit-tree", f"{head}^{{tree}}", "-p", head, "-m", message).strip()
    if not (head and new and git("-C", str(repo), "update-ref", "HEAD", new, head).returncode == 0):
        print(f"roadmap.py: could not record '{message}' in {repo}", file=sys.stderr)


def commit(path: pathlib.Path, message: str) -> None:
    """Commit this one file, alone, in its own repository."""
    repo = private_repo(path)
    if repo is None:
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
                raise Duplicate(args.dedup_key, owner)
        rid = roadmap.next_id()
        key = f"Dedup-Key: {args.dedup_key}" if args.dedup_key else ""
        source = " · ".join(v for v in (args.source, args.proof or "", key) if v)
        days = EXPIRY_DAYS.get(args.klass)
        ablauf = (args.today + dt.timedelta(days=days)).isoformat() if days else "nie"
        cells = [rid, args.klass, cell(args.title), "neu", cell(source)]
        cells += [cell(args.ledger or ""), "—", "—", ablauf, "—"]
        roadmap.insert_row("Neu", Row(cells))
        return rid

    path = roadmap_path(args.file)
    try:
        rid = write(path, change, verb="add", delta=1, today=args.today)
    except Duplicate as e:
        # The refusal leaves its trace for `stats` (the dedup quote): an empty
        # commit, nothing else.
        commit_empty(path, f"roadmap: dedup {e.key} -> {e.owner}")
        raise
    print(rid)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    roadmap = Roadmap.load(roadmap_path(args.file))
    if args.wip:
        print(wip_text(roadmap.counts(args.today)))
        return 0
    if args.id:
        section, row = roadmap.find(args.id)
        print(f"{row.id} · {section}")
        for name, value in zip(COLUMNS[1:], row.cells[1:], strict=True):
            print(f"  {name}: {value}")
        return 0
    rows = roadmap.rows()
    for line in next_up(roadmap):
        print(line)
    print()
    print(wip_text(roadmap.counts(args.today)))
    for name in SECTIONS[1:]:
        mine = [r for s, r in rows if s == name]
        print(f"\n{name} ({len(mine)})")
        if name in ("Abgeschlossen", "Archiv"):
            continue  # history: the count is the overview
        for r in mine:
            title = r.cells[TITEL] if r.well_formed else r.text()
            title = title if len(title) <= 90 else title[:89] + "…"
            klasse = r.cells[KLASSE] if r.well_formed else "?"
            print(f"  {r.id}  {klasse:<4}  {r.cells[STATUS] if r.well_formed else '?'}  {title}")
    return 0


def next_up(roadmap: Roadmap) -> list[str]:
    """The "Als Nächstes" section as Kevin wrote it, heading included."""
    try:
        start, end = roadmap.section_bounds("Als Nächstes")
    except UsageError:
        return []
    lines = [i if isinstance(i, str) else i.text() for i in roadmap.items[start:end]]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def components_of(row: Row) -> set[str]:
    """What a row touches: the `Komponente:` lines of its ledger and the
    component field of its Dedup-Key (<klasse>:<komponente>:…)."""
    found = set()
    key = row.dedup_key
    if key and key.count(":") >= 1:
        found.add(key.split(":")[1])
    ledger = row.cells[LEDGER]
    file = (ROOT / ledger).resolve()
    # Only a ledger of this repository: a stray absolute path reads nothing.
    if ledger not in ("", "—", "-") and file.is_relative_to(ROOT.resolve()):
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            text = ""
        found |= set(re.findall(r"^Komponente:\s*([^\s·]+)", text, re.MULTILINE))
    return found


def cmd_next(args: argparse.Namespace) -> int:
    rows = [r for _, r in Roadmap.load(roadmap_path(args.file)).rows() if r.well_formed]
    done = {r.id for r in rows if r.state == "abgeschlossen"}
    excluded = set(args.exclude_components or ())
    ready = [
        (CLASS_RANK.get(r.cells[KLASSE], len(CLASSES)), i, r)
        for i, r in enumerate(rows)
        if r.state == args.status
        and all(dep in done for dep in ROW_ID.findall(r.cells[DEPENDS]))
        and not components_of(r) & excluded
    ]
    if not ready:
        print(f"next: no {args.status} row is ready", file=sys.stderr)
        return 1
    _, _, r = min(ready, key=lambda c: (c[0], c[1]))
    ledger = f" ({r.cells[LEDGER]})" if r.cells[LEDGER] not in ("", "—", "-") else ""
    print(f"{r.id} {r.cells[KLASSE]} {r.cells[TITEL]}{ledger}")
    return 0


def merged_prs() -> dict[int, dt.date]:
    """PR number -> the day it was merged, from gh in this repository."""
    cmd = ["gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json", "number,mergedAt"]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused(74, f"gh pr list could not run: {e}") from None
    if r.returncode != 0:
        raise Refused(74, f"gh pr list failed: {r.stderr.strip()}")
    try:
        return {
            int(pr["number"]): dt.date.fromisoformat(pr["mergedAt"][:10])
            for pr in json.loads(r.stdout)
        }
    except (ValueError, KeyError, TypeError) as e:
        raise Refused(74, f"gh pr list answered something else: {e}") from None


def to_close(roadmap: Roadmap, merged: dict[int, dt.date]) -> list[tuple[str, list[int]]]:
    """Open rows whose PR column names PRs that are all merged."""
    out = []
    for _, r in roadmap.rows():
        nums = [int(n) for n in re.findall(r"#(\d+)", r.cells[PR])] if r.well_formed else []
        if r.is_open and nums and all(n in merged for n in nums):
            out.append((r.id, nums))
    return out


def cmd_sync(args: argparse.Namespace) -> int:
    path = roadmap_path(args.file)
    merged = merged_prs()

    def change(roadmap: Roadmap) -> str:
        # Again under the lock: another sync may have closed them meanwhile.
        closed = to_close(roadmap, merged)
        if not closed:
            raise NothingToClose
        for rid, nums in closed:
            note = ", ".join(f"PR #{n}" for n in nums)
            day = max(merged[n] for n in nums)
            roadmap.set_status(rid, "abgeschlossen", note, day, check=False)
        return " ".join(rid for rid, _ in closed)

    try:
        # Checked without the lock first: nothing to do must not wait for it,
        # nor be refused by the 5 s rule.
        if not to_close(Roadmap.load(path), merged):
            raise NothingToClose
        print(f"sync: closed {write(path, change, verb='sync', delta=0, today=args.today)}")
    except NothingToClose:
        print("sync: no open row with a merged PR")
    repo = repo_of(path)
    if repo and repo != ROOT.resolve():
        print(f"sync: not pushed — push it yourself: git -C {repo} push")
    return 0


def window(since: dt.date, until: dt.date) -> tuple[str, str]:
    """git log bounds for whole UTC days. Without an offset git reads them in
    the local zone of whoever runs it, and the same question would count a
    commit near midnight on one machine and not on the next."""
    return (
        f"--since={since.isoformat()}T00:00:00+00:00",
        f"--until={until.isoformat()}T23:59:59+00:00",
    )


def tasks_closed(since: dt.date, until: dt.date) -> int:
    """Ledger tasks ticked [x] in this repository's history, net of un-ticks."""
    log = git_out(
        ROOT, "log", "-p", *window(since, until), "--format=", "--", "tasks/*.md",
    )  # fmt: skip
    added = len(re.findall(r"^\+###\s.*\[x\]", log, re.MULTILINE))
    removed = len(re.findall(r"^-###\s.*\[x\]", log, re.MULTILINE))
    return added - removed


def waits(path: pathlib.Path) -> dict[str, list[float]]:
    """Days each row spent in a state it has left, from the file's own history."""
    repo = repo_of(path)
    if repo is None:
        return {}
    rel = str(path.resolve().relative_to(repo))
    since: dict[str, tuple[str, dt.datetime]] = {}
    out: dict[str, list[float]] = defaultdict(list)
    for line in git_out(repo, "log", "--reverse", "--format=%H %cI", "--", rel).splitlines():
        sha, when = line.split()
        t = dt.datetime.fromisoformat(when)
        for _, r in Roadmap(git_out(repo, "show", f"{sha}:{rel}")).rows():
            if not r.well_formed:
                continue
            prev = since.get(r.id)
            if prev is None:
                since[r.id] = (r.state, t)
            elif prev[0] != r.state:
                out[prev[0]].append((t - prev[1]).total_seconds() / 86400)
                since[r.id] = (r.state, t)
    return out


def cmd_stats(args: argparse.Namespace) -> int:
    path = roadmap_path(args.file)
    roadmap = Roadmap.load(path)
    rows = [r for _, r in roadmap.rows() if r.well_formed]
    since = args.today - dt.timedelta(days=args.days - 1)
    n = tasks_closed(since, args.today)
    print(f"tasks/day: {n / args.days:.1f} ({n} closed in the last {args.days} days)")
    mins = [
        int(m.group(0))
        for r in rows
        if "#" in r.cells[PR] and (m := re.match(r"\d+", r.cells[KEVIN_MIN]))
    ]
    if mins:
        print(f"kevin-min/PR: {sum(mins) / len(mins):.0f} ({len(mins)} PRs)")
    else:
        print("kevin-min/PR: — (no row with a PR carries minutes)")
    spent = waits(path)
    for state in [s for s in STATE_ORDER if s in spent]:
        days = spent[state]
        print(f"wait {state}: {sum(days) / len(days):.1f} d ({len(days)} rows)")
    if not spent:
        print("wait: — (no history of state changes)")
    alt, open_rows = roadmap.counts(args.today)["ALT"], sum(r.is_open for r in rows)
    print(f"stale: {alt}/{open_rows} open rows past their Ablauf ({percent(alt, open_rows)})")
    adds, dups = adds_and_dedups(path, since, args.today)
    if adds + dups:
        print(
            f"dedup: {dups}/{adds + dups} adds refused as duplicates ({percent(dups, adds + dups)})"
        )
    else:
        print(f"dedup: — (no add in the last {args.days} days)")
    return 0


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


def adds_and_dedups(path: pathlib.Path, since: dt.date, until: dt.date) -> tuple[int, int]:
    """`roadmap: add` and `roadmap: dedup` commits of the file's repository."""
    repo = repo_of(path)
    if repo is None:
        return 0, 0
    subjects = git_out(
        repo, "log", *window(since, until), "--format=%s",
    ).splitlines()  # fmt: skip
    return (
        sum(s.startswith("roadmap: add ") for s in subjects),
        sum(s.startswith("roadmap: dedup ") for s in subjects),
    )


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
    sh = sub.add_parser("show", help="one row, the WIP counters, or the overview")
    sh.add_argument("id", nargs="?")
    sh.add_argument("--wip", action="store_true", help="only the WIP counters, from the rows")
    sh.set_defaults(func=cmd_show)
    nx = sub.add_parser("next", help="the next row to build")
    nx.add_argument("--status", default="freigegeben", choices=sorted(SECTION_OF))
    nx.add_argument("--exclude-components", nargs="+", metavar="C", help="skip rows touching these")
    nx.set_defaults(func=cmd_next)
    sub.add_parser("sync", help="close rows whose PRs are merged").set_defaults(func=cmd_sync)
    sa = sub.add_parser("stats", help="tasks/day, Kevin-min/PR, wait per state, stale, dedup")
    sa.add_argument("--days", type=int, default=30, help="the window for tasks/day (default 30)")
    sa.set_defaults(func=cmd_stats)
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
