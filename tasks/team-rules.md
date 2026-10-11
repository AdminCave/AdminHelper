<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Team-Plan Phase 1, Schritt 2: die Regeln des Teams in CLAUDE.md §2/§3 — Task-Ledger
Status: aktiv · Branch: harness/team-rules · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-10-10 (Stufen-Plan, im Chat mit der Aufsicht; Roadmap R-0270). Offene Fragen: 1 Zeilenbudget <= 226 jetzt, per Test festgeschrieben, <= 185 spaeter als eigene Zeile R-0271 (Kevin); 2 Deckel aktiv 2 in Code und Status, Disjunkt-Pflicht bleibt (Aufsicht); 3 roter main: Revert des letzten Merges, flaky heisst Rerun plus Roadmap-Zeile (Kevin) - der Satz kommt in den Text; 4 Tagesbericht erst mit seiner Stufe, der Chef uebernimmt seinen Stand aus AH-STATUS, Roadmap und Ledgern (Kevin); 5 oeffentlicher Wortlaut des Restrisikos allgemein (Aufsicht); 6 1 VM-Lauf meint Laeufe, keine stehende Warm-Box (Aufsicht)
Spec: docs/features/team-rules.md (Roadmap: die Zeile legt der Chef an)
Heavy: none — Regeltext, Python und Shell unter scripts/dev mit hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-10 von Worker A für die Aufsicht (adminhelper-ac). Ein Stufen-Plan, den Kevin freigibt; den PR
merged Kevin, denn er ändert §2/§3. Zeilenangaben origin/main@d2a654cd; beim Bau an Symbolen orientieren. Der
Wortlaut für CLAUDE.md steht in der Spec, „Der Entwurf für CLAUDE.md“. Kevins Antworten auf die offenen Fragen der
Spec gehen vor dem Bau in diesen Wortlaut ein.

### T1 — CLAUDE.md §2/§3/§6/§8 nach dem Entwurf, CHANGELOG  [ ]
Komponente: scripts · Dateien: CLAUDE.md, CHANGELOG.md, scripts/tests/skill_consistency_test.sh
Änderung:
- `CLAUDE.md:25–97` (§2) wird der Entwurf der Spec. §3 Trigger 3 (`:112–113`) und der letzte Satz der Schweigeregel
  (`:123`), §6 (`:174–175`) und §8 (`:203`) ändern sich wie dort.
- CLAUDE.md hat danach höchstens 226 Zeilen.
- CHANGELOG `[Unreleased]` bekommt unter Changed: Regeln des Teams (Chef, Team unter Kevins UID, Deckel, Modelle,
  Merge, Triage, Dauerlauf erst nach der Sandbox).
- Ein neuer Abschnitt in `skill_consistency_test.sh` hält fest, was nicht still verschwinden darf:
  - die Regel „Vor jedem unbeaufsichtigten Dauerlauf kommt die Sandbox“;
  - der Chef mit seiner Brücke „bisher „Aufsicht““;
  - „Nie prüft Sonnet, was Sonnet baute“;
  - höchstens 226 Zeilen, wenn Kevin offene Frage 1 so beantwortet.
  Jede Prüfung zeigt erst an einer Fixture, dass sie fallen kann (wie die übrigen dort).
Rot vorher: Der neue Abschnitt fällt auf main, weil weder Chef noch Sandbox-Regel dastehen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: CHANGELOG.md (Changed)

### T2 — Deckel `aktiv` 2 im Code, die vier Stellen gleich  [ ]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/hooks/session-status.sh, .claude/skills/roadmap/SKILL.md, scripts/dev/tests/test_roadmap.py, scripts/tests/session_status_test.sh, scripts/tests/heavy_test.sh, scripts/tests/skill_consistency_test.sh
Änderung:
- `WIP_CAPS` in `roadmap.py:151` und `session-status.sh:119` setzt `aktiv` auf 2; die Kommentare `session-status.sh:35`
  und `:117` ziehen nach. Der `/roadmap`-Skill (`:36`) nennt `aktiv` 2.
- Die Tests, die `aktiv` 1 festhalten, gehen auf den neuen Deckel. Gemessen mit einem Probelauf mit `aktiv` 2 auf
  d2a654cd sind das:
  - `test_roadmap.py`: 4 Tests;
  - `session_status_test.sh`: 2 Prüfungen, `:170` und `:312`. Der Fall „Deckel erreicht“ bekommt zwei `aktiv`-Zeilen,
    damit er den erreichten Deckel weiter prüft;
  - `heavy_test.sh`: 1 Prüfung, `:512`.
- Ein Paritätstest in `skill_consistency_test.sh` hält zusammen: die Deckel in CLAUDE.md §3 Trigger 3, `roadmap.py`
  `WIP_CAPS`, `session-status.sh` `WIP_CAPS` und den `/roadmap`-Skill. Er zeigt an einer Fixture, dass er bei einer
  abweichenden Zahl fällt.
Assertion-Änderung: scripts/dev/tests/test_roadmap.py::test_show_wip_counts_the_rows_not_the_header — der Deckel `aktiv` ist 2 (Kevin, 2 Bau-Slots)
Assertion-Änderung: scripts/dev/tests/test_roadmap.py::test_show_the_overview — der Deckel `aktiv` ist 2 (Kevin, 2 Bau-Slots)
Assertion-Änderung: scripts/dev/tests/test_roadmap.py::test_the_header_follows_the_move — der Kopf zählt gegen `aktiv` 2
Assertion-Änderung: scripts/dev/tests/test_roadmap.py::test_add_appends_a_neu_row_and_touches_nothing_else — der neu gerechnete Kopf zählt gegen `aktiv` 2
Rot vorher: Der Paritätstest fällt, sobald CLAUDE.md (T1) `aktiv` 2 sagt und der Code noch 1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Regel steht in T1)
Abhängt von: T1

### T3 — Skills und AUTONOMOUS.md: die Einzeiler gegen die neuen Regeln  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-build/SKILL.md, .claude/skills/test/SKILL.md, AUTONOMOUS.md, scripts/tests/skill_consistency_test.sh
Änderung: Die Zeilen aus der Tabelle „Widersprüche“ der Spec, je eine:
- `feature-plan/SKILL.md:232`: Zwei Bau-Slots sind der Deckel; eine Lane nur für disjunkte Ledger.
- `feature-plan/SKILL.md:191`: Eine neue Zeile legt das Gate nur für ein Vorhaben an, das Kevin diktiert oder
  angenommen hat; ein eigener Fund bleibt `neu` bis zu Kevins Bestätigung.
- `feature-build/SKILL.md:281`: Der Review am Ende läuft auf Opus, nicht nach `review.sh risk`.
- `test/SKILL.md:277` und `AUTONOMOUS.md:370`: Das „no docker“ wird zu einem richtigen Grund (`bootstrap_linux.sh`
  baut die Maschine um, auf der es läuft).
- `skill_consistency_test.sh` prüft, dass der Review über den ganzen Branch in `feature-build` Opus nennt, mit
  Fixture-Gegenprobe.
- `skill_consistency_test` bleibt grün.
Rot vorher: Die neue Prüfung fällt auf main (`:281` nennt `review.sh risk`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md (eine Zeile)
Abhängt von: T1
