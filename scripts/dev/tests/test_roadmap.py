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
import pathlib
import sys

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
