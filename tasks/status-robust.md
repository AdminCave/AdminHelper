<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket status-robust: status übersteht eine entartete state.json und liest seine Dateien nur direkt (R-0343) — Task-Ledger
Status: freigegeben · Branch: harness/status-robust · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; T2 fuer beide Dateien; Bau nach der Uebergabe von skip-per-step; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0343 (Kurz-Ledger ohne Spec)
Heavy: none — ledger-loop.sh status mit ledger_loop_test (Fixture-Dateien); kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat das Paket am 2026-10-13 angenommen.
Zeilenangaben origin/main@bef5d17e; beim Bau an Symbolen orientieren.

Vorab geprüft (Python 3.13.5, die Version der Dev-Box):
- `ledger-loop.sh status` liest state.json mit `json.loads(capped(…))` (:199) und fängt `(OSError, ValueError)` (:202).
  - `json.loads("[" * 100000)` wirft `RecursionError`, kein `ValueError`. Die Datei ist 100 KB groß, liegt also unter
    der Grenze von 1 MiB.
  - Ergebnis: ein Traceback statt einer Worker-Zeile, im AH-STATUS-Block steht dann nur `Worker: ?`.
  - Bei Tiefe 5000 kommt ein `JSONDecodeError`, der schon gefangen wird.
- Die Kosten (:212) prüft `type(c) in (int, float) and math.isfinite(c) and 0 <= c < 1e6`.
  - `math.isfinite(10**400)` wirft `OverflowError` („int too large to convert to float“).
  - In der Reihenfolge `0 <= c < 1e6` zuerst vergleicht Python Ganzzahl und Gleitkomma exakt und liefert `False`, ohne
    Überlauf.
- `capped()` (:175–187) öffnet mit `os.O_RDONLY | os.O_NONBLOCK` und folgt damit einem Symlink im letzten Pfadteil. Das
  betrifft state.json (:199) und die neueste `summary-*.md` (:229). Beide schreibt der Loop selbst als reguläre Dateien.

### T1 — status fängt die Rekursionsgrenze und prüft den Kostenbereich vor isfinite  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung:
- Das Laden von state.json (:199–203) fängt zusätzlich `RecursionError`. Das Ergebnis ist
  `Worker: ? (state.json unlesbar)`.
- Die Kostenprüfung (:212) wird `type(c) in (int, float) and 0 <= c < 1e6 and math.isfinite(c)`. Ein Wert außerhalb
  des Bereichs ist `?`, ohne Überlauf.
- Fälle in ledger_loop_test:
  - eine state.json aus 100 000 `[` → genau `Worker: ? (state.json unlesbar)`, kein Traceback;
  - `{"stop": null, "cost_usd": 1` + 400 Nullen + `}` → erste Zeile `Worker: läuft · ? $ · seit ?`, kein Traceback.
Rot vorher: Auf main endet beides mit einem Traceback (`RecursionError` bzw. `OverflowError`) ohne Worker-Zeile.
Beweis: origin/main@bef5d17e, ledger-loop.sh :202 `except (OSError, ValueError):`, :212 `math.isfinite(c) and 0 <= c
< 1e6`. Fund: Review status-classes, Worker A, 2026-10-13; der Reviewer hat den Kostenfall gegengeprüft.
Dedup-Key: bug:scripts:ledger-loop.sh:status
HEAD: bef5d17e
Semantik: session-status.sh, Kopf: „a SessionStart hook that fails or blocks would break every session“; die erste Zeile
von `status` steht im AH-STATUS (AUTONOMOUS.md :283–284).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — status liest state.json und die Summary nicht über einen Symlink  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung:
- `capped()` öffnet zusätzlich mit `os.O_NOFOLLOW`. Ein Symlink im letzten Pfadteil gibt `OSError` und wird behandelt
  wie eine Datei, die keine reguläre ist:
  - state.json → `Worker: ? (state.json unlesbar)`;
  - die neueste Summary → übergangen, wie eine FIFO heute.
- Der Kommentar von `capped()` nennt den Grund: Beide Dateien schreibt der Loop selbst als reguläre Dateien, und
  `status` liest nur sie.
- Fälle in ledger_loop_test:
  - die neueste `summary-*.md` als Symlink auf eine Datei mit der Zeile `Stop: plchold-marker` → die erste Zeile kommt,
    `plchold-marker` steht nirgends in der Ausgabe;
  - state.json als Symlink auf eine gültige state.json → `Worker: ? (state.json unlesbar)`.
Rot vorher: Auf main erscheint `plchold-marker` in der Ausgabe von `status`, und ein Symlink als state.json wird gelesen.
Beweis: origin/main@bef5d17e, ledger-loop.sh :178 `os.open(path, os.O_RDONLY | os.O_NONBLOCK)`. Fund: Review
status-classes, Worker A, 2026-10-13.
HEAD: bef5d17e
Semantik: ledger-loop.sh, Kommentar von `capped()`: „A regular file of at most n bytes, judged on the open descriptor“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T1
