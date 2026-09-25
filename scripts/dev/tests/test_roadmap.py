# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hermetic tests for scripts/dev/roadmap.py.

Every roadmap here is a fixture written into tmp_path — never
tasks/private/ROADMAP.md, which is Kevin's file. The fixtures are synthetic:
the style of the real file (header, "Als Nächstes", the eight sections, notes
behind the status word), none of its content.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import pathlib
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import roadmap  # noqa: E402  (the path has to exist before the import)

TODAY = dt.date(2026, 9, 25)
HEAD = "| ID | Klasse | Titel | Status | Quelle / Beweis | Ledger | Hängt ab von | PR | Ablauf | Kevin-min |"
SEP = "|---|---|---|---|---|---|---|---|---|---|"


def row(
    rid: str,
    status: str,
    klasse: str = "FEAT",
    title: str = "Etwas",
    source: str = "kevin 2026-09-01",
    ablauf: str = "—",
) -> str:
    return f"| {rid} | {klasse} | {title} | {status} | {source} | — | — | — | {ablauf} | — |"


def doc(
    sections: dict[str, list[str]], wip: str = "aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 2/20 · ALT: 0"
) -> str:
    out = [
        "# Fixture — Roadmap",
        f"Stand: 2026-09-20 · WIP: {wip}",
        "Klassen: SEC(P0) > REG(P1) > REL(P2) > BUG(P3) > FEAT(P4) > REF(P5) > IDEE(P6)",
        "",
        "## Als Nächstes",
        "1. R-0003 erst das, dann das",
        "2. Kevin, Handarbeit: irgendwas",
    ]
    for heading, rows in sections.items():
        out += ["", f"## {heading}"]
        if rows:
            out += [HEAD, SEP, *rows]
    return "\n".join(out) + "\n"


def clean_sections() -> dict[str, list[str]]:
    return {
        "In Arbeit": [row("R-0004", "aktiv (T2/5)", title="Etwas Großes")],
        "Neu (untriagiert)": [
            row(
                "R-0006",
                "neu",
                "REF",
                "Doppelter Helfer",
                "weekly 2026-09-19 · Dedup-Key: ref:web:src/a.ts:helper",
                ablauf="2026-12-18",
            ),
            row("R-0005", "neu", "BUG", "Ein Fehler", "hunt 2026-09-18", ablauf="nie"),
        ],
        "Geplant (Stufen in Reihenfolge)": [row("R-0003", "geplant"), row("R-0007", "freigegeben")],
        "Zurückgestellt": [row("R-0009", "zurückgestellt", "IDEE")],
        "Blockiert": [],
        "Abgeschlossen (letzte 30 Tage)": [
            row("R-0002", "abgeschlossen 2026-09-15 (PR #3, Merge abc1234)", "BUG"),
            row("R-0008", "abgelehnt 2026-09-14 (kein Bedarf)", "IDEE"),
        ],
        "Archiv": [row("R-0001", "abgeschlossen 2026-07-01")],
    }


CLEAN = doc(clean_sections())


def write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "ROADMAP.md"
    p.write_bytes(text.encode("utf-8"))
    return p


def line_of(text: str, needle: str, nth: int = 1) -> int:
    """The line number of the nth line containing needle — what lint has to name."""
    hits = [n for n, line in enumerate(text.split("\n"), 1) if needle in line]
    return hits[nth - 1]


def findings(text: str) -> list[str]:
    return [str(f) for f in roadmap.lint(roadmap.Roadmap(text), TODAY)]


# ── the parser ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        CLEAN,
        CLEAN.rstrip("\n"),  # no newline at the end
        CLEAN.replace("\n", "\r\n"),
        CLEAN + "\n\n   \nEin Absatz Prosa am Ende, mit | einem Strich.\n",
        CLEAN.replace("| Etwas Großes |", "| Regex `(e\\|_ne)?!` im Titel |"),
        CLEAN.replace("| Etwas Großes |", "| Etwas | mit Strich |"),  # eleven columns
        CLEAN.replace(SEP, "| --- | :--- | ---: |---|---|---|---|---|---|---|"),
        "",
    ],
    ids=[
        "clean",
        "no-final-newline",
        "crlf",
        "prose",
        "escaped-pipe",
        "eleven-columns",
        "separator",
        "empty",
    ],
)
def test_a_roundtrip_without_a_change_is_byte_identical(text: str) -> None:
    assert roadmap.Roadmap(text).render() == text


def test_rows_are_the_table_rows_and_nothing_else() -> None:
    rows = roadmap.Roadmap(CLEAN).rows()
    assert [(s, r.id) for s, r in rows] == [
        ("In Arbeit", "R-0004"),
        ("Neu", "R-0006"),
        ("Neu", "R-0005"),
        ("Geplant", "R-0003"),
        ("Geplant", "R-0007"),
        ("Zurückgestellt", "R-0009"),
        ("Abgeschlossen", "R-0002"),
        ("Abgeschlossen", "R-0008"),
        ("Archiv", "R-0001"),
    ]


def test_the_status_is_the_first_word_and_the_rest_a_note() -> None:
    rows = dict((r.id, r) for _, r in roadmap.Roadmap(CLEAN).rows())
    assert rows["R-0004"].status == "aktiv"
    assert rows["R-0002"].status == "abgeschlossen"


def test_an_escaped_pipe_stays_in_its_cell() -> None:
    text = CLEAN.replace("| Etwas Großes |", "| Regex `(e\\|_ne)?!` im Titel |")
    r = roadmap.Roadmap(text).rows()[0][1]
    assert r.well_formed and r.cells[roadmap.TITEL] == "Regex `(e\\|_ne)?!` im Titel"


# ── lint ──────────────────────────────────────────────────────────────────────


def test_a_clean_roadmap_lints_clean() -> None:
    assert findings(CLEAN) == []


def test_a_duplicate_id() -> None:
    s = clean_sections()
    s["Neu (untriagiert)"].append(row("R-0005", "neu", "BUG", "Nochmal vergeben"))
    text = doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 3/20 · ALT: 0")
    first, again = line_of(text, "| Ein Fehler |"), line_of(text, "Nochmal vergeben")
    assert findings(text) == [f"R-0005 line {again}: duplicate ID (first at line {first})"]


def test_an_unknown_status() -> None:
    text = CLEAN.replace(
        "| R-0003 | FEAT | Etwas | geplant |", "| R-0003 | FEAT | Etwas | angedacht |"
    )
    assert findings(text) == [
        f"R-0003 line {line_of(text, 'angedacht')}: unknown status 'angedacht'"
    ]


@pytest.mark.parametrize(
    ("alias", "means"), [("geparkt", "zurückgestellt"), ("erledigt", "abgeschlossen")]
)
def test_an_alias_is_named(alias: str, means: str) -> None:
    old = (
        "| R-0009 | IDEE | Etwas | zurückgestellt |"
        if alias == "geparkt"
        else "| R-0002 | BUG | Etwas | abgeschlossen"
    )
    new = (
        f"| R-0009 | IDEE | Etwas | {alias} |"
        if alias == "geparkt"
        else f"| R-0002 | BUG | Etwas | {alias}"
    )
    text = CLEAN.replace(old, new)
    assert text != CLEAN
    [f] = findings(text)
    assert f"status '{alias}' is an alias, write '{means}'" in f


def test_a_row_in_the_wrong_section() -> None:
    s = clean_sections()
    s["Archiv"].append(row("R-0010", "neu", "REF", "Vergessen im Archiv"))
    text = doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 3/20 · ALT: 0")
    n = line_of(text, "Vergessen im Archiv")
    assert findings(text) == [f"R-0010 line {n}: status 'neu' belongs in 'Neu', not 'Archiv'"]


def test_a_closed_row_may_be_in_the_archive_but_not_in_progress() -> None:
    s = clean_sections()
    s["In Arbeit"].append(row("R-0010", "abgeschlossen 2026-09-01"))
    text = doc(s)
    n = line_of(text, "| R-0010 |")
    assert findings(text) == [
        f"R-0010 line {n}: status 'abgeschlossen' belongs in 'Abgeschlossen', not 'In Arbeit'"
    ]


def test_a_row_with_the_wrong_number_of_columns() -> None:
    text = CLEAN.replace("| Etwas Großes |", "| Etwas | mit Strich |")
    # Its own finding, and the header then counts one aktiv row less: the row
    # is unreadable, and that is said rather than guessed around.
    assert findings(text) == [
        "header line 2: WIP says aktiv 1, the rows say 0",
        f"R-0004 line {line_of(text, 'mit Strich')}: 11 columns, expected 10",
    ]


def test_a_row_with_a_stray_pipe_still_holds_its_id() -> None:
    s = clean_sections()
    s["In Arbeit"][0] = row("R-0004", "aktiv", title="Etwas | mit Strich")
    s["Neu (untriagiert)"].append(row("R-0004", "neu", "BUG", "Später vergeben"))
    text = doc(s, wip="aktiv 0/1 · bereit 0/2 · pr 0/3 · neu 3/20 · ALT: 0")
    first, again = line_of(text, "mit Strich"), line_of(text, "Später vergeben")
    assert findings(text) == [
        f"R-0004 line {first}: 11 columns, expected 10",
        f"R-0004 line {again}: duplicate ID (first at line {first})",
    ]


def test_a_pipe_line_that_is_no_row_is_reported_not_skipped() -> None:
    text = CLEAN.replace("## Blockiert\n", "## Blockiert\n| siehe Kommentar im PR\n")
    assert findings(text) == [
        f"row line {line_of(text, 'siehe Kommentar')}: 1 columns, expected 10"
    ]


def test_a_dedup_key_two_open_rows_share() -> None:
    s = clean_sections()
    s["Neu (untriagiert)"].append(
        row(
            "R-0010",
            "neu",
            "REF",
            "Derselbe Helfer",
            "weekly 2026-09-20 · Dedup-Key: ref:web:src/a.ts:helper",
        )
    )
    text = doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 3/20 · ALT: 0")
    n = line_of(text, "Derselbe Helfer")
    assert findings(text) == [
        f"R-0010 line {n}: Dedup-Key 'ref:web:src/a.ts:helper' is already on R-0006"
    ]


def test_a_dedup_key_on_a_closed_row_does_not_count() -> None:
    s = clean_sections()
    s["Abgeschlossen (letzte 30 Tage)"].append(
        row(
            "R-0010",
            "abgeschlossen 2026-09-10",
            "REF",
            "Früher schon",
            "weekly 2026-09-01 · Dedup-Key: ref:web:src/a.ts:helper",
        )
    )
    assert findings(doc(s)) == []


def test_a_wip_header_the_rows_do_not_add_up_to() -> None:
    text = CLEAN.replace("neu 2/20", "neu 7/20").replace("ALT: 0", "ALT: 3")
    assert findings(text) == [
        "header line 2: WIP says neu 7, the rows say 2",
        "header line 2: WIP says ALT 3, the rows say 0",
    ]


def test_alt_counts_open_rows_past_their_expiry() -> None:
    s = clean_sections()
    s["Neu (untriagiert)"][1] = row("R-0005", "neu", "BUG", "Ein Fehler", ablauf="2026-09-24")
    s["Abgeschlossen (letzte 30 Tage)"][0] = row(
        "R-0002", "abgeschlossen 2026-09-15", ablauf="2026-01-01"
    )
    assert findings(doc(s)) == ["header line 2: WIP says ALT 0, the rows say 1"]


def test_an_ablauf_that_is_no_date_expires_nothing() -> None:
    s = clean_sections()
    s["Neu (untriagiert)"][1] = row("R-0005", "neu", "BUG", "Ein Fehler", ablauf="2026-13-45")
    assert findings(doc(s)) == []


def test_no_wip_header() -> None:
    text = CLEAN.replace(
        "Stand: 2026-09-20 · WIP: aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 2/20 · ALT: 0",
        "Stand: gestern",
    )
    # Named at the Stand line it expected the counters on.
    assert findings(text) == ["header line 2: no 'Stand: … · WIP: …' line above the first section"]


def test_a_roadmap_in_the_style_of_today_reports_exactly_its_faults() -> None:
    """The two faults the stocktaking of 2026-09-23 found (spec): an ID given
    twice by hand, and `neu` rows left in the archive. Nothing else."""
    s = clean_sections()
    s["Neu (untriagiert)"].insert(
        0, row("R-0047", "neu", "REF", "Von heavy.sh", "weekly 2026-09-19")
    )
    s["Abgeschlossen (letzte 30 Tage)"].insert(
        0, row("R-0047", "abgeschlossen 2026-09-20", "BUG", "Von Hand gezählt")
    )
    s["Archiv"] += [
        row("R-0030", "neu", "IDEE", "Alt und vergessen"),
        row("R-0031", "neu", "REF", "Auch vergessen"),
    ]
    text = doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 5/20 · ALT: 0")
    assert findings(text) == [
        f"R-0047 line {line_of(text, 'Von Hand gezählt')}: duplicate ID (first at line {line_of(text, 'Von heavy.sh')})",
        f"R-0030 line {line_of(text, 'Alt und vergessen')}: status 'neu' belongs in 'Neu', not 'Archiv'",
        f"R-0031 line {line_of(text, 'Auch vergessen')}: status 'neu' belongs in 'Neu', not 'Archiv'",
    ]


# ── the command line ──────────────────────────────────────────────────────────


def test_lint_exits_0_on_a_clean_file(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = write(tmp_path, CLEAN)
    assert roadmap.main(["--file", str(p), "--today", "2026-09-25", "lint"]) == 0
    assert capsys.readouterr().out.strip() == f"lint: {p} ok"


def test_lint_exits_1_and_prints_one_line_per_finding(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = write(tmp_path, CLEAN.replace("neu 2/20", "neu 7/20").replace("ALT: 0", "ALT: 3"))
    assert roadmap.main(["--file", str(p), "--today", "2026-09-25", "lint"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "header line 2: WIP says neu 7, the rows say 2",
        "header line 2: WIP says ALT 3, the rows say 0",
    ]


def test_ah_roadmap_names_the_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = write(tmp_path, CLEAN)
    monkeypatch.setenv("AH_ROADMAP", str(p))
    assert roadmap.main(["--today", "2026-09-25", "lint"]) == 0
    assert str(p) in capsys.readouterr().out


def test_file_wins_over_ah_roadmap(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AH_ROADMAP", str(tmp_path / "elsewhere.md"))
    assert roadmap.roadmap_path(str(tmp_path / "given.md")) == tmp_path / "given.md"


def test_without_either_it_is_the_private_roadmap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AH_ROADMAP", raising=False)
    assert roadmap.roadmap_path(None) == roadmap.ROOT / "tasks" / "private" / "ROADMAP.md"


def test_a_missing_file_is_exit_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert roadmap.main(["--file", str(tmp_path / "nope.md"), "lint"]) == 2
    assert "no such file" in capsys.readouterr().err


def test_a_bad_date_is_exit_2(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit) as e:
        roadmap.main(["--file", str(write(tmp_path, CLEAN)), "--today", "gestern", "lint"])
    assert e.value.code == 2


# ── add: writing under the lock ──────────────────────────────────────────────

SCRIPT = pathlib.Path(roadmap.__file__)
ADD = ["--class", "REG", "--title", "Schritt rot", "--source", "weekly 2026-09-25 · 1a2b3c4d"]


def aged(p: pathlib.Path, seconds: int = 60) -> pathlib.Path:
    """Back-date the file: a fixture just written looks like a hand edit."""
    t = time.time() - seconds
    os.utime(p, (t, t))
    return p


def add(p: pathlib.Path, *args: str) -> int:
    return roadmap.main(["--file", str(p), "--today", "2026-09-25", "add", *args])


def spawn_add(p: pathlib.Path, title: str) -> subprocess.Popen[str]:
    cmd = [sys.executable, str(SCRIPT), "--file", str(p), "--today", "2026-09-25", "add"]
    cmd += ["--class", "BUG", "--title", title, "--source", "hunt 2026-09-25"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


NEW_HEADER = "Stand: 2026-09-25 · WIP: aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 3/20 · ALT: 0"
OLD_HEADER = "Stand: 2026-09-20 · WIP: aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 2/20 · ALT: 0"


def test_add_appends_a_neu_row_and_touches_nothing_else(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = aged(write(tmp_path, CLEAN))
    rc = add(p, "--class", "REF", "--title", "Toter Helfer", "--source", "find:dead 2026-09-25",
             "--proof", "find/2026-09-25@1a2b3c4", "--dedup-key", "ref:web:src/b.ts:old",
             "--ledger", "tasks/toter-helfer.md")  # fmt: skip
    assert rc == 0
    assert capsys.readouterr().out.strip() == "R-0010"
    new = (
        "| R-0010 | REF | Toter Helfer | neu | find:dead 2026-09-25 · find/2026-09-25@1a2b3c4 · "
        "Dedup-Key: ref:web:src/b.ts:old | tasks/toter-helfer.md | — | — | 2026-12-24 | — |"
    )
    text = p.read_text(encoding="utf-8")
    # Byte for byte the old file, plus the row at the end of "Neu" and the new header.
    assert text.replace(new + "\n", "").replace(NEW_HEADER, OLD_HEADER) == CLEAN
    rows = [r.id for s, r in roadmap.Roadmap(text).rows() if s == "Neu"]
    assert rows == ["R-0006", "R-0005", "R-0010"]
    assert findings(text) == []
    assert (tmp_path / "ROADMAP.md.bak").read_text(encoding="utf-8") == CLEAN


def test_the_id_is_the_highest_of_all_rows_plus_one(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = clean_sections()
    s["Archiv"].append(row("R-0040", "abgeschlossen 2026-06-01"))
    p = aged(write(tmp_path, doc(s)))
    assert add(p, *ADD) == 0
    assert capsys.readouterr().out.strip() == "R-0041"


@pytest.mark.parametrize(
    ("klasse", "ablauf"), [("REG", "nie"), ("IDEE", "2026-11-24"), ("REF", "2026-12-24")]
)
def test_the_ablauf_follows_the_class(tmp_path: pathlib.Path, klasse: str, ablauf: str) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, "--class", klasse, "--title", "x", "--source", "kevin 2026-09-25") == 0
    [new] = [
        r for _, r in roadmap.Roadmap(p.read_text(encoding="utf-8")).rows() if r.id == "R-0010"
    ]
    assert new.cells[roadmap.ABLAUF] == ablauf


def test_a_pipe_in_the_title_is_escaped(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, "--class", "BUG", "--title", "a | b", "--source", "kevin 2026-09-25") == 0
    text = p.read_text(encoding="utf-8")
    [new] = [r for _, r in roadmap.Roadmap(text).rows() if r.id == "R-0010"]
    assert new.well_formed and new.cells[roadmap.TITEL] == "a \\| b"
    assert findings(text) == []


def test_a_neu_section_without_a_table_gets_one(tmp_path: pathlib.Path) -> None:
    s = clean_sections()
    s["Neu (untriagiert)"] = []
    p = aged(write(tmp_path, doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 0/20 · ALT: 0")))
    assert add(p, *ADD) == 0
    text = p.read_text(encoding="utf-8")
    assert f"## Neu (untriagiert)\n{HEAD}\n{SEP}\n| R-0010 |" in text
    assert findings(text) == []


def test_the_neu_cap_refuses_the_21st(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s = clean_sections()
    s["Neu (untriagiert)"] = [row(f"R-01{n:02d}", "neu", "BUG") for n in range(20)]
    text = doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 20/20 · ALT: 0")
    p = aged(write(tmp_path, text))
    assert add(p, *ADD) == 3
    assert "neu cap is reached (20/20)" in capsys.readouterr().err
    assert p.read_text(encoding="utf-8") == text
    assert not (tmp_path / "ROADMAP.md.bak").exists()


def test_an_open_dedup_key_is_refused_and_named(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD, "--dedup-key", "ref:web:src/a.ts:helper") == 4
    assert "already on open row R-0006" in capsys.readouterr().err
    assert p.read_text(encoding="utf-8") == CLEAN


def test_the_dedup_key_of_a_closed_row_is_free(tmp_path: pathlib.Path) -> None:
    s = clean_sections()
    s["Abgeschlossen (letzte 30 Tage)"].append(
        row(
            "R-0010",
            "abgeschlossen 2026-09-10",
            "REF",
            "Früher",
            "weekly 2026-09-01 · Dedup-Key: reg:step-x",
        )
    )
    p = aged(write(tmp_path, doc(s)))
    assert add(p, *ADD, "--dedup-key", "reg:step-x") == 0


@pytest.mark.parametrize("flag", ["--title", "--source"])
def test_an_empty_title_or_source_is_refused(tmp_path: pathlib.Path, flag: str) -> None:
    p = aged(write(tmp_path, CLEAN))
    args = ["--class", "BUG", "--title", "t", "--source", "s"]
    args[args.index(flag) + 1] = "  "
    assert add(p, *args) == 2
    assert p.read_text(encoding="utf-8") == CLEAN


def test_a_dedup_key_is_one_token(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD, "--dedup-key", "reg: zwei worte") == 2
    assert p.read_text(encoding="utf-8") == CLEAN


def test_a_file_just_changed_by_hand_is_refused(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = write(tmp_path, CLEAN)  # mtime: now, and roadmap.py never wrote it
    assert add(p, *ADD) == 5
    assert "not by roadmap.py" in capsys.readouterr().err
    assert p.read_text(encoding="utf-8") == CLEAN


def test_its_own_last_write_is_no_reason_to_wait(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 0
    assert add(p, *ADD) == 0
    assert capsys.readouterr().out.split() == ["R-0010", "R-0011"]


def test_a_hand_edit_after_its_own_write_is_refused(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 0
    p.write_text(p.read_text(encoding="utf-8") + "Notiz von Hand\n", encoding="utf-8")
    assert add(p, *ADD) == 5


def test_a_hand_edit_in_the_same_clock_tick_is_still_a_hand_edit(tmp_path: pathlib.Path) -> None:
    """The mtime moves in ticks of a few ms: an edit right after roadmap.py's
    own write can carry the very same mtime_ns. Forced here, not waited for."""
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 0
    own = p.stat().st_mtime_ns
    p.write_text(p.read_text(encoding="utf-8") + "Notiz von Hand\n", encoding="utf-8")
    os.utime(p, ns=(own, own))
    assert add(p, *ADD) == 5


def test_a_write_that_loses_a_row_is_undone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real = roadmap.write_text

    def loses_the_last_row(path: pathlib.Path, text: str) -> None:
        lines = text.split("\n")
        last = max(i for i, line in enumerate(lines) if line.startswith("| R-"))
        real(path, "\n".join(lines[:last] + lines[last + 1 :]))

    monkeypatch.setattr(roadmap, "write_text", loses_the_last_row)
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 6
    assert "restored from" in capsys.readouterr().err
    assert p.read_text(encoding="utf-8") == CLEAN


def test_a_writer_waits_for_the_lock(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    with open(tmp_path / "ROADMAP.md.lock", "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        proc = spawn_add(p, "Wartet")
        time.sleep(1.0)
        assert proc.poll() is None, proc.communicate()
        assert p.read_text(encoding="utf-8") == CLEAN
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err
    assert out.strip() == "R-0010"


def test_two_adds_at_once_get_two_ids(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    procs = [spawn_add(p, f"Parallel {n}") for n in range(2)]
    results = [proc.communicate(timeout=30) for proc in procs]
    assert [proc.returncode for proc in procs] == [0, 0], results
    assert sorted(out.strip() for out, _ in results) == ["R-0010", "R-0011"]
    text = p.read_text(encoding="utf-8")
    assert "Parallel 0" in text and "Parallel 1" in text
    assert findings(text) == []


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def fixture_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "private"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "commit.gpgsign", "false")
    write(repo, CLEAN)
    (repo / "other.md").write_text("etwas anderes\n", encoding="utf-8")
    git(repo, "add", "ROADMAP.md", "other.md")
    git(repo, "commit", "-qm", "seed")
    return repo


def test_add_commits_the_file_alone(tmp_path: pathlib.Path) -> None:
    repo = fixture_repo(tmp_path)
    (repo / "other.md").write_text("halb fertig, gestagt\n", encoding="utf-8")
    git(repo, "add", "other.md")
    p = aged(repo / "ROADMAP.md")
    assert add(p, *ADD) == 0
    assert git(repo, "log", "-1", "--format=%s").strip() == "roadmap: add R-0010"
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["ROADMAP.md"]
    # The staged edit of another file is still staged, not swept into the commit.
    assert git(repo, "diff", "--cached", "--name-only").split() == ["other.md"]
    assert git(repo, "status", "--porcelain", "--", "ROADMAP.md") == ""


def test_outside_a_repository_it_writes_but_does_not_commit(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 0
    assert "no git repository — not committed" in capsys.readouterr().err
    assert "| R-0010 |" in p.read_text(encoding="utf-8")


def test_it_never_commits_in_the_public_repository(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = fixture_repo(tmp_path)
    monkeypatch.setattr(roadmap, "ROOT", repo)
    assert add(aged(repo / "ROADMAP.md"), *ADD) == 0
    assert "public repository — not committed" in capsys.readouterr().err
    assert git(repo, "log", "-1", "--format=%s").strip() == "seed"


# ── status and approve: the section follows the status ───────────────────────


def status(p: pathlib.Path, *args: str) -> int:
    return roadmap.main(["--file", str(p), "--today", "2026-09-25", "status", *args])


def approve(p: pathlib.Path, *args: str) -> int:
    return roadmap.main(["--file", str(p), "--today", "2026-09-25", "approve", *args])


def placed(p: pathlib.Path, rid: str) -> tuple[str, roadmap.Row]:
    [hit] = [
        (s, r) for s, r in roadmap.Roadmap(p.read_text(encoding="utf-8")).rows() if r.id == rid
    ]
    return hit


def with_probe(state: str) -> str:
    """CLEAN plus R-0020 in `state`, filed in the section it belongs to."""
    s = clean_sections()
    home = roadmap.SECTION_OF[state]
    [key] = [k for k in s if roadmap.section_name("## " + k) == home]
    value = f"{state} 2026-09-20" if state in roadmap.CLOSED else state
    s[key].append(row("R-0020", value, "BUG", "Die Probe"))
    return doc(s)


STATES = sorted(roadmap.TRANSITIONS)
ALLOWED = [(a, b) for a in STATES for b in sorted(roadmap.TRANSITIONS[a])]
FORBIDDEN = [(a, b) for a in STATES for b in STATES if b != a and b not in roadmap.TRANSITIONS[a]]


@pytest.mark.parametrize(("old", "new"), ALLOWED, ids=[f"{a}->{b}" for a, b in ALLOWED])
def test_an_allowed_transition_moves_the_row_home(
    tmp_path: pathlib.Path, old: str, new: str
) -> None:
    p = aged(write(tmp_path, with_probe(old)))
    assert status(p, "R-0020", new) == 0
    section, r = placed(p, "R-0020")
    assert (section, r.status) == (roadmap.SECTION_OF[new], new)
    assert findings(p.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(("old", "new"), FORBIDDEN, ids=[f"{a}->{b}" for a, b in FORBIDDEN])
def test_a_forbidden_transition_is_exit_2(tmp_path: pathlib.Path, old: str, new: str) -> None:
    text = with_probe(old)
    p = aged(write(tmp_path, text))
    assert status(p, "R-0020", new) == 2
    assert p.read_text(encoding="utf-8") == text


def test_closed_to_neu_in_particular_is_forbidden(
    capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
) -> None:
    p = aged(write(tmp_path, with_probe("abgeschlossen")))
    assert status(p, "R-0020", "neu") == 2
    assert (
        "abgeschlossen -> neu is no transition (from abgeschlossen: abgelehnt)"
        in capsys.readouterr().err
    )


def test_the_life_of_a_row(tmp_path: pathlib.Path) -> None:
    """The live probe of the Abschluss, on a fixture repository: every step one
    commit, and the throwaway row ends abgelehnt so it counts for nothing."""
    repo = fixture_repo(tmp_path)
    p = aged(repo / "ROADMAP.md")
    assert add(p, "--class", "FEAT", "--title", "Wegwerf", "--source", "kevin 2026-09-25") == 0
    for step in (["status", "R-0010", "geplant"], ["approve", "R-0010"], ["status", "R-0010", "aktiv"],
                 ["status", "R-0010", "bereit"], ["status", "R-0010", "pr"],
                 ["status", "R-0010", "abgeschlossen", "--note", "PR #99"],
                 ["status", "R-0010", "abgelehnt", "--note", "Probe"]):  # fmt: skip
        assert roadmap.main(["--file", str(p), "--today", "2026-09-25", *step]) == 0, step
    section, r = placed(p, "R-0010")
    assert (section, r.cells[roadmap.STATUS]) == ("Abgeschlossen", "abgelehnt 2026-09-25 (Probe)")
    assert git(repo, "log", "--format=%s", "-8").splitlines() == [
        "roadmap: status R-0010 abgelehnt",
        "roadmap: status R-0010 abgeschlossen",
        "roadmap: status R-0010 pr",
        "roadmap: status R-0010 bereit",
        "roadmap: status R-0010 aktiv",
        "roadmap: approve R-0010",
        "roadmap: status R-0010 geplant",
        "roadmap: add R-0010",
    ]
    assert findings(p.read_text(encoding="utf-8")) == []


def test_a_closed_status_carries_its_day_and_note_at_the_top(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, with_probe("pr")))
    assert status(p, "R-0020", "abgeschlossen", "--note", "PR #7, Merge 1a2b3c4") == 0
    rows = [
        r for s, r in roadmap.Roadmap(p.read_text(encoding="utf-8")).rows() if s == "Abgeschlossen"
    ]
    assert rows[0].id == "R-0020"
    assert rows[0].cells[roadmap.STATUS] == "abgeschlossen 2026-09-25 (PR #7, Merge 1a2b3c4)"


def test_the_same_status_again_files_a_row_and_keeps_it(tmp_path: pathlib.Path) -> None:
    s = clean_sections()
    lost = row("R-0010", "neu", "REF", "Im Archiv vergessen", ablauf="2026-12-01")
    s["Archiv"].append(lost)
    p = aged(write(tmp_path, doc(s, wip="aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 3/20 · ALT: 0")))
    assert status(p, "R-0010", "neu") == 0
    section, r = placed(p, "R-0010")
    assert section == "Neu" and r.text() == lost  # moved, not rewritten
    assert findings(p.read_text(encoding="utf-8")) == []


def test_the_same_status_again_keeps_its_note(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert status(p, "R-0004", "aktiv") == 0
    assert placed(p, "R-0004")[1].cells[roadmap.STATUS] == "aktiv (T2/5)"


def test_an_alias_becomes_the_word(tmp_path: pathlib.Path) -> None:
    s = clean_sections()
    s["Archiv"].append(row("R-0010", "geparkt", "IDEE", "Geparkt im Archiv"))
    p = aged(write(tmp_path, doc(s)))
    assert status(p, "R-0010", "zurückgestellt") == 0
    section, r = placed(p, "R-0010")
    assert (section, r.cells[roadmap.STATUS]) == ("Zurückgestellt", "zurückgestellt")


def test_a_closed_alias_keeps_its_day_note_and_place(tmp_path: pathlib.Path) -> None:
    """The cleanup of the real file turns `erledigt` into `abgeschlossen`: the
    day it closed and its note are history, not something to overwrite."""
    s = clean_sections()
    s["Archiv"].insert(0, row("R-0010", "erledigt 2026-06-01 (PR #12)", "BUG", "Alt"))
    p = aged(write(tmp_path, doc(s)))
    assert status(p, "R-0010", "abgeschlossen") == 0
    rows = roadmap.Roadmap(p.read_text(encoding="utf-8")).rows()
    assert [r.id for sec, r in rows if sec == "Archiv"] == ["R-0010", "R-0001"]
    assert placed(p, "R-0010")[1].cells[roadmap.STATUS] == "abgeschlossen 2026-06-01 (PR #12)"


def test_a_new_note_on_a_closed_row_keeps_its_day(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert status(p, "R-0002", "abgeschlossen", "--note", "PR #3, nachgetragen") == 0
    assert (
        placed(p, "R-0002")[1].cells[roadmap.STATUS]
        == "abgeschlossen 2026-09-15 (PR #3, nachgetragen)"
    )


def test_a_table_emptied_by_a_move_takes_the_next_row(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert status(p, "R-0009", "geplant") == 0  # "Zurückgestellt" keeps only its table head
    assert status(p, "R-0003", "zurückgestellt") == 0
    assert f"## Zurückgestellt\n{HEAD}\n{SEP}\n| R-0003 |" in p.read_text(encoding="utf-8")


def test_the_header_follows_the_move(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert status(p, "R-0004", "bereit") == 0
    assert (
        "Stand: 2026-09-25 · WIP: aktiv 0/1 · bereit 1/2 · pr 0/3 · neu 2/20 · ALT: 0"
        in p.read_text(encoding="utf-8")
    )


def test_closed_rows_older_than_30_days_go_to_the_top_of_the_archive(
    tmp_path: pathlib.Path,
) -> None:
    s = clean_sections()
    kept, older = (
        row("R-0011", "abgeschlossen 2026-08-26 (30 Tage)", "BUG"),
        row("R-0012", "abgeschlossen 2026-08-25 (31 Tage)", "BUG"),
    )
    s["Abgeschlossen (letzte 30 Tage)"] = [
        row("R-0002", "abgeschlossen 2026-09-15", "BUG"),
        kept,
        older,
        row("R-0013", "abgelehnt 2026-08-01", "IDEE"),
        row("R-0014", "abgeschlossen (Datum fehlt)", "BUG"),
    ]
    p = aged(write(tmp_path, doc(s)))
    assert status(p, "R-0003", "freigegeben") == 0  # any write archives
    text = p.read_text(encoding="utf-8")
    rows = roadmap.Roadmap(text).rows()
    assert [r.id for sec, r in rows if sec == "Abgeschlossen"] == ["R-0002", "R-0011", "R-0014"]
    assert [r.id for sec, r in rows if sec == "Archiv"] == ["R-0012", "R-0013", "R-0001"]
    assert older in text.split("\n")  # moved byte for byte


def test_approve_and_revoke(tmp_path: pathlib.Path) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert approve(p, "R-0003") == 0
    assert placed(p, "R-0003")[1].status == "freigegeben"
    assert approve(p, "R-0003", "--revoke") == 0
    assert placed(p, "R-0003")[1].status == "geplant"


@pytest.mark.parametrize(
    ("rid", "args"), [("R-0005", []), ("R-0003", ["--revoke"]), ("R-0007", [])]
)
def test_approve_only_from_geplant_and_revoke_only_from_freigegeben(
    tmp_path: pathlib.Path, rid: str, args: list[str]
) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert approve(p, rid, *args) == 2
    assert p.read_text(encoding="utf-8") == CLEAN


@pytest.mark.parametrize(
    ("text", "rid", "says"),
    [
        (CLEAN, "R-0099", "no row R-0099"),
        (CLEAN.replace("| R-0009 |", "| R-0005 |"), "R-0005", "R-0005 is on 2 rows"),
        (
            CLEAN.replace("| Etwas Großes |", "| Etwas | Großes |"),
            "R-0004",
            "R-0004 has 11 columns",
        ),
        (CLEAN.replace("| geplant |", "| angedacht |"), "R-0003", "unknown status 'angedacht'"),
    ],
    ids=["unknown-id", "duplicate-id", "eleven-columns", "unknown-status"],
)
def test_a_row_status_cannot_safely_touch_is_exit_2(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str], text: str, rid: str, says: str
) -> None:
    p = aged(write(tmp_path, text))
    assert status(p, rid, "zurückgestellt") == 2
    assert says in capsys.readouterr().err
    assert p.read_text(encoding="utf-8") == text


# ── show, next, sync, stats ──────────────────────────────────────────────────


def run(p: pathlib.Path, *args: str, today: str = "2026-09-25") -> int:
    return roadmap.main(["--file", str(p), "--today", today, *args])


def test_show_is_read_only(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = write(tmp_path, CLEAN)  # just written: a writer would refuse it, show must not care
    for args in ([], ["R-0004"], ["--wip"]):
        assert run(p, "show", *args) == 0
    assert p.read_text(encoding="utf-8") == CLEAN
    assert sorted(f.name for f in tmp_path.iterdir()) == ["ROADMAP.md"]


def test_show_wip_counts_the_rows_not_the_header(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = write(tmp_path, CLEAN.replace("neu 2/20", "neu 7/20"))
    assert run(p, "show", "--wip") == 0
    assert capsys.readouterr().out == "WIP: aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 2/20 · ALT: 0\n"


def test_show_one_row(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write(tmp_path, CLEAN), "show", "R-0006") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "R-0006 · Neu"
    assert "  Quelle / Beweis: weekly 2026-09-19 · Dedup-Key: ref:web:src/a.ts:helper" in out
    assert "  Ablauf: 2026-12-18" in out


def test_show_the_overview(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    long = "Ein Titel, der so lang ist, dass ihn die Übersicht kürzen muss, damit eine Zeile eine Zeile bleibt"
    p = write(tmp_path, CLEAN.replace("| Etwas Großes |", f"| {long} |"))
    assert run(p, "show") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:3] == [
        "## Als Nächstes",
        "1. R-0003 erst das, dann das",
        "2. Kevin, Handarbeit: irgendwas",
    ]
    assert "WIP: aktiv 1/1 · bereit 0/2 · pr 0/3 · neu 2/20 · ALT: 0" in out
    assert "  R-0004  FEAT  aktiv (T2/5)  " + long[:89] + "…" in out
    assert "  R-0005  BUG   neu  Ein Fehler" in out
    # History is counted, not listed.
    i = out.index("Abgeschlossen (2)")
    assert out[i + 1 : i + 3] == ["", "Archiv (1)"]


def next_fixture(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> pathlib.Path:
    monkeypatch.setattr(roadmap, "ROOT", tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "bug.md").write_text(
        "# Bug — Task-Ledger\n\n### T1 — x  [ ]\nKomponente: server · Dateien: a.py\n",
        encoding="utf-8",
    )
    s = clean_sections()
    s["Geplant (Stufen in Reihenfolge)"] += extra
    return write(tmp_path, doc(s))


FREIGEGEBEN = [
    row("R-0021", "freigegeben", "FEAT", "Ein Feature"),
    "| R-0022 | BUG | Erster Bug | freigegeben | hunt 2026-09-20 | tasks/bug.md | — | — | nie | — |",
    row(
        "R-0023",
        "freigegeben",
        "BUG",
        "Zweiter Bug",
        "weekly 2026-09-21 · Dedup-Key: bug:web:src/x.ts:f",
    ),
    "| R-0024 | SEC | Wartet auf Stufe X | freigegeben | kevin 2026-09-22 | — | R-0003 | — | nie | — |",
]


def test_next_takes_the_class_then_the_order_and_waits_for_dependencies(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = next_fixture(tmp_path, monkeypatch, FREIGEGEBEN)
    # R-0024 is SEC, but it depends on R-0003 (geplant); R-0021 is only a FEAT.
    assert run(p, "next") == 0
    assert capsys.readouterr().out == "R-0022 BUG Erster Bug (tasks/bug.md)\n"


def test_next_takes_a_row_whose_dependency_is_done(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = next_fixture(
        tmp_path, monkeypatch, [f.replace("| R-0003 |", "| R-0002 |") for f in FREIGEGEBEN]
    )
    assert run(p, "next") == 0
    assert capsys.readouterr().out.startswith("R-0024 SEC")


def test_next_skips_excluded_components(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    p = next_fixture(tmp_path, monkeypatch, FREIGEGEBEN)
    # server: from the ledger of R-0022; web: from the Dedup-Key of R-0023. Of
    # the FEATs left, R-0007 stands first.
    assert run(p, "next", "--exclude-components", "server", "web") == 0
    assert capsys.readouterr().out == "R-0007 FEAT Etwas\n"


def test_next_by_another_status(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(write(tmp_path, CLEAN), "next", "--status", "geplant") == 0
    assert capsys.readouterr().out.startswith("R-0003 FEAT")


def test_next_with_nothing_ready_is_exit_1(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(write(tmp_path, CLEAN.replace("| freigegeben |", "| geplant |")), "next") == 1
    assert "no freigegeben row is ready" in capsys.readouterr().err


def fake_gh(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, body: str, rc: int = 0
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\ncat <<'JSON'\n{body}\nJSON\nexit {rc}\n", encoding="utf-8")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


MERGED = '[{"number": 7, "mergedAt": "2026-09-24T10:00:00Z"}, {"number": 3, "mergedAt": "2026-09-15T08:00:00Z"}]'


def sync_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = fixture_repo(tmp_path)
    s = clean_sections()
    s["In Arbeit"] = [
        "| R-0004 | FEAT | Etwas Großes | pr | kevin 2026-09-01 | — | — | #7 | — | 15 |",
        "| R-0010 | BUG | Zwei PRs | pr | kevin 2026-09-02 | — | — | #7, #9 | — | — |",
    ]
    write(repo, doc(s))
    git(repo, "commit", "-qam", "two prs")
    return aged(repo / "ROADMAP.md")


def test_sync_closes_the_rows_whose_prs_are_all_merged(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(tmp_path, monkeypatch, MERGED)
    p = sync_fixture(tmp_path)
    assert run(p, "sync") == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "sync: closed R-0004",
        f"sync: not pushed — push it yourself: git -C {p.parent.resolve()} push",
    ]
    section, r = placed(p, "R-0004")
    assert (section, r.cells[roadmap.STATUS]) == (
        "Abgeschlossen",
        "abgeschlossen 2026-09-24 (PR #7)",
    )
    assert placed(p, "R-0010")[1].status == "pr"  # PR #9 is not merged
    assert (
        placed(p, "R-0002")[1].cells[roadmap.STATUS]
        == "abgeschlossen 2026-09-15 (PR #3, Merge abc1234)"
    )
    assert git(p.parent, "log", "-1", "--format=%s").strip() == "roadmap: sync R-0004"
    assert findings(p.read_text(encoding="utf-8")) == []


def test_sync_with_nothing_to_close_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(tmp_path, monkeypatch, '[{"number": 3, "mergedAt": "2026-09-15T08:00:00Z"}]')
    p = aged(write(tmp_path, CLEAN))
    assert run(p, "sync") == 0
    assert capsys.readouterr().out.startswith("sync: no open row with a merged PR")
    assert p.read_text(encoding="utf-8") == CLEAN
    assert not (tmp_path / "ROADMAP.md.bak").exists()


def test_sync_without_an_answer_from_gh_is_exit_74(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(tmp_path, monkeypatch, "not logged in", rc=1)
    p = aged(write(tmp_path, CLEAN))
    assert run(p, "sync") == 74
    assert "gh pr list failed" in capsys.readouterr().err
    assert p.read_text(encoding="utf-8") == CLEAN


def dated_commit(repo: pathlib.Path, when: str, message: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", message], check=True, env=env)


def ledger_text(t1: str, t2: str) -> str:
    return f"# X — Task-Ledger\n\n### T1 — eins  [{t1}]\nKomponente: server\n\n### T2 — zwei  [{t2}]\nKomponente: server\n"


def test_stats_on_a_repository_of_three_commits(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = fixture_repo(tmp_path)
    monkeypatch.setattr(roadmap, "ROOT", repo)  # the ledgers live here too
    (repo / "tasks").mkdir()
    s = clean_sections()

    def state(r10: str, r11: str) -> None:
        s["Neu (untriagiert)"] = [row("R-0010", r10, "BUG", "Zehn")] if r10 == "neu" else []
        s["Geplant (Stufen in Reihenfolge)"] = (
            [row("R-0010", r10, "BUG", "Zehn")] if r10 != "neu" else []
        )
        s["In Arbeit"] = [row("R-0011", r11, "FEAT", "Elf")] if r11 == "aktiv" else []
        s["Geplant (Stufen in Reihenfolge)"] += (
            [row("R-0011", r11, "FEAT", "Elf")] if r11 != "aktiv" else []
        )
        s["Abgeschlossen (letzte 30 Tage)"] = [
            "| R-0002 | BUG | Etwas | abgeschlossen 2026-09-15 | kevin | — | — | #3 | — | 12 |",
            "| R-0008 | FEAT | Etwas | abgeschlossen 2026-09-14 | kevin | — | — | #5 | — | 20 |",
            "| R-0012 | REF | Ohne PR | abgeschlossen 2026-09-14 | kevin | — | — | — | — | 99 |",
        ]
        s["Zurückgestellt"] = [row("R-0009", "zurückgestellt", "IDEE", "Alt", ablauf="2026-09-01")]
        write(repo, doc(s))

    state("neu", "geplant")
    (repo / "tasks" / "x.md").write_text(ledger_text(" ", " "), encoding="utf-8")
    dated_commit(repo, "2026-09-20T10:00:00+02:00", "one")
    state("geplant", "geplant")
    (repo / "tasks" / "x.md").write_text(ledger_text("x", " "), encoding="utf-8")
    dated_commit(repo, "2026-09-22T10:00:00+02:00", "two")
    state("freigegeben", "aktiv")
    (repo / "tasks" / "x.md").write_text(ledger_text("x", "x"), encoding="utf-8")
    dated_commit(repo, "2026-09-23T10:00:00+02:00", "three")

    assert run(repo / "ROADMAP.md", "stats", "--days", "10") == 0
    assert capsys.readouterr().out.splitlines() == [
        "tasks/day: 0.2 (2 closed in the last 10 days)",
        "kevin-min/PR: 16 (2 PRs)",
        "wait neu: 2.0 d (1 rows)",
        "wait geplant: 2.0 d (2 rows)",
        "stale: 1/3 open rows past their Ablauf (33%)",
        "dedup: — (no add in the last 10 days)",
    ]


def test_a_refused_duplicate_leaves_one_empty_commit_and_counts(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = fixture_repo(tmp_path)
    p = repo / "ROADMAP.md"
    today = dt.date.today().isoformat()
    assert run(aged(p), "add", *ADD, today=today) == 0
    # A hand edit of the file and a staged edit elsewhere: neither may ride along.
    p.write_text(p.read_text(encoding="utf-8") + "Notiz von Hand\n", encoding="utf-8")
    aged(p)
    (repo / "other.md").write_text("gestagt\n", encoding="utf-8")
    git(repo, "add", "other.md")
    before = git(repo, "rev-list", "--count", "HEAD")
    assert run(p, "add", *ADD, "--dedup-key", "ref:web:src/a.ts:helper", today=today) == 4
    assert int(git(repo, "rev-list", "--count", "HEAD")) == int(before) + 1
    assert (
        git(repo, "log", "-1", "--format=%s").strip()
        == "roadmap: dedup ref:web:src/a.ts:helper -> R-0006"
    )
    assert git(repo, "show", "--name-only", "--format=", "HEAD").strip() == ""
    assert sorted(git(repo, "status", "--porcelain", "--untracked-files=no").splitlines()) == [
        " M ROADMAP.md",
        "M  other.md",
    ]
    capsys.readouterr()
    assert run(p, "stats", today=today) == 0
    assert "dedup: 1/2 adds refused as duplicates (50%)" in capsys.readouterr().out.splitlines()


def test_a_renamed_done_task_is_not_closed_twice(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = fixture_repo(tmp_path)
    monkeypatch.setattr(roadmap, "ROOT", repo)
    (repo / "tasks").mkdir()
    ledger = repo / "tasks" / "x.md"
    ledger.write_text(ledger_text(" ", " "), encoding="utf-8")
    dated_commit(repo, "2026-09-20T10:00:00+02:00", "one")
    ledger.write_text(ledger_text("x", " "), encoding="utf-8")
    dated_commit(repo, "2026-09-21T10:00:00+02:00", "two")
    # A later edit of a ticked heading shows in `git log -p` as - and + of an [x].
    ledger.write_text(
        ledger_text("x", " ").replace("T1 — eins", "T1 — eins, genauer"), encoding="utf-8"
    )
    dated_commit(repo, "2026-09-22T10:00:00+02:00", "three")
    assert run(repo / "ROADMAP.md", "stats", "--days", "10") == 0
    assert (
        capsys.readouterr().out.splitlines()[0] == "tasks/day: 0.1 (1 closed in the last 10 days)"
    )


@pytest.mark.parametrize("tz", ["UTC", "Asia/Tokyo", "America/Los_Angeles"])
def test_the_stats_window_is_the_same_in_every_time_zone(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tz: str,
) -> None:
    monkeypatch.setenv("TZ", tz)
    repo = fixture_repo(tmp_path)
    monkeypatch.setattr(roadmap, "ROOT", repo)
    (repo / "tasks").mkdir()
    ledger = repo / "tasks" / "x.md"
    ledger.write_text(ledger_text(" ", " "), encoding="utf-8")
    dated_commit(repo, "2026-09-10T10:00:00+00:00", "one")
    ledger.write_text(ledger_text("x", " "), encoding="utf-8")
    dated_commit(repo, "2026-09-16T01:00:00+02:00", "two")  # 2026-09-15 23:00 UTC: outside
    ledger.write_text(ledger_text("x", "x"), encoding="utf-8")
    dated_commit(repo, "2026-09-16T03:00:00+02:00", "three")  # 2026-09-16 01:00 UTC: inside
    assert run(repo / "ROADMAP.md", "stats", "--days", "10") == 0
    assert (
        capsys.readouterr().out.splitlines()[0] == "tasks/day: 0.1 (1 closed in the last 10 days)"
    )


def test_a_sync_that_finds_the_work_done_under_the_lock_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(tmp_path, monkeypatch, MERGED)
    p = sync_fixture(tmp_path)
    real, calls = roadmap.to_close, []

    def closed_meanwhile(
        rm: roadmap.Roadmap, merged: dict[int, dt.date]
    ) -> list[tuple[str, list[int]]]:
        calls.append(1)  # the check without the lock still sees R-0004 open
        return real(rm, merged) if len(calls) == 1 else []

    monkeypatch.setattr(roadmap, "to_close", closed_meanwhile)
    head = git(p.parent, "rev-parse", "HEAD")
    assert run(p, "sync") == 0
    assert capsys.readouterr().out.startswith("sync: no open row with a merged PR")
    assert len(calls) == 2
    assert git(p.parent, "rev-parse", "HEAD") == head
    assert not (p.parent / "ROADMAP.md.bak").exists()


def test_next_reads_no_ledger_outside_the_repository(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("Komponente: server\n", encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(roadmap, "ROOT", root)
    s = clean_sections()
    s["Geplant (Stufen in Reihenfolge)"] = [
        f"| R-0022 | BUG | Draußen | freigegeben | hunt 2026-09-20 | {outside} | — | — | nie | — |"
    ]
    assert run(write(root, doc(s)), "next", "--exclude-components", "server") == 0
    assert capsys.readouterr().out.startswith("R-0022 BUG")


# ── from the review of the whole branch ──────────────────────────────────────


def test_sync_closes_only_rows_in_pr_and_reports_the_rest(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stage with several PRs is `aktiv` while one of them is merged: sync
    must not close it, and nothing can take a close back."""
    fake_gh(tmp_path, monkeypatch, MERGED)
    repo = fixture_repo(tmp_path)
    s = clean_sections()
    s["In Arbeit"] = [
        "| R-0004 | FEAT | Eine Stufe | aktiv (5a gemergt, 5b offen) | kevin | — | — | #7 | — | — |",
        "| R-0010 | BUG | Fertig | pr | kevin | — | — | #7 | — | — |",
    ]
    write(repo, doc(s))
    git(repo, "commit", "-qam", "a stage and a pr")
    p = aged(repo / "ROADMAP.md")
    assert run(p, "sync") == 0
    out = capsys.readouterr().out.splitlines()
    assert "sync: closed R-0010" in out
    assert "sync: PR #7 merged, but R-0004 is aktiv — not closed" in out
    assert placed(p, "R-0004")[1].cells[roadmap.STATUS] == "aktiv (5a gemergt, 5b offen)"


def test_sync_with_only_rows_outside_pr_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(tmp_path, monkeypatch, MERGED)
    text = CLEAN.replace(
        "| aktiv (T2/5) | kevin 2026-09-01 | — | — | — |",
        "| aktiv (T2/5) | kevin 2026-09-01 | — | — | #7 |",
    )
    p = aged(write(tmp_path, text))
    assert run(p, "sync") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:2] == [
        "sync: PR #7 merged, but R-0004 is aktiv — not closed",
        "sync: no open row with a merged PR to close (sync closes rows in pr only)",
    ]
    assert p.read_text(encoding="utf-8") == text
    assert not (tmp_path / "ROADMAP.md.bak").exists()


def test_no_commit_in_a_clone_whose_private_dir_is_a_plain_directory(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second clone of the public repository without its own private repo:
    tasks/private is a plain, ignored directory, and its HEAD is the clone's."""
    clone = tmp_path / "clone"
    clone.mkdir()
    git(clone, "init", "-q")
    git(clone, "config", "user.email", "fixture@example.invalid")
    git(clone, "config", "user.name", "Fixture")
    git(clone, "config", "commit.gpgsign", "false")
    (clone / ".gitignore").write_text("tasks/private/\n", encoding="utf-8")
    git(clone, "add", ".gitignore")
    git(clone, "commit", "-qm", "seed")
    private = clone / "tasks" / "private"
    private.mkdir(parents=True)
    p = aged(write(private, CLEAN))
    head = git(clone, "rev-parse", "HEAD")
    assert add(p, *ADD) == 0
    assert add(p, *ADD, "--dedup-key", "ref:web:src/a.ts:helper") == 4
    assert git(clone, "rev-parse", "HEAD") == head
    assert "is not the root of its own repository — not committed" in capsys.readouterr().err


def test_the_dedup_record_is_written_under_the_lock(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = []

    def probe(path: pathlib.Path, message: str) -> None:
        # Another open file description: a lock held by write() refuses it.
        with open(tmp_path / "ROADMAP.md.lock", "a+") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except BlockingIOError:
                held.append(True)

    monkeypatch.setattr(roadmap, "commit_empty", probe)
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD, "--dedup-key", "ref:web:src/a.ts:helper") == 4
    assert held == [True]


def test_an_id_that_vanished_by_hand_is_not_given_again(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p = aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 0
    # An editor saves an old buffer, well after the 5 s: R-0010 is gone again.
    aged(write(tmp_path, CLEAN))
    assert add(p, *ADD) == 0
    assert capsys.readouterr().out.split() == ["R-0010", "R-0011"]


def test_an_add_rolled_back_by_the_row_count_check_uses_no_id(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 6 undoes the add: the ID it drew was never issued, so the next add
    takes it, not the one after."""
    real = roadmap.write_text

    def loses_the_last_row(path: pathlib.Path, text: str) -> None:
        lines = text.split("\n")
        last = max(i for i, line in enumerate(lines) if line.startswith("| R-"))
        real(path, "\n".join(lines[:last] + lines[last + 1 :]))

    p = aged(write(tmp_path, CLEAN))
    monkeypatch.setattr(roadmap, "write_text", loses_the_last_row)
    assert add(p, *ADD) == 6
    monkeypatch.setattr(roadmap, "write_text", real)
    assert add(p, *ADD) == 0
    assert capsys.readouterr().out.split() == ["R-0010"]


@pytest.mark.parametrize(
    ("key", "ledger", "components"),
    [
        ("reg:web-vitest", "", set()),  # a step, not a component
        ("rel:deps-audit", "", set()),
        ("ref:web:src/a.ts:helper", "", {"web"}),
        ("", "tasks/reg.md", set()),  # Komponente: (aus dem Schritt ableiten)
    ],
)
def test_only_a_real_component_is_a_component(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    ledger: str,
    components: set[str],
) -> None:
    monkeypatch.setattr(roadmap, "ROOT", tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "reg.md").write_text(
        "### R1 — x  [ ]\nKomponente: (aus dem Schritt ableiten)\n", encoding="utf-8"
    )
    source = f"weekly 2026-09-25 · Dedup-Key: {key}" if key else "weekly 2026-09-25"
    [(_, r)] = roadmap.Roadmap(
        doc(
            {
                "Neu": [
                    row("R-0010", "neu", "REG", "x", source).replace(
                        "| — | — | — | — |", f"| {ledger or '—'} | — | — | — |", 1
                    )
                ]
            }
        )
    ).rows()
    assert roadmap.components_of(r) == components
