<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# roadmap.py: neue Zeilen ohne neu-Deckel — Task-Ledger
Status: erledigt · Branch: feature/roadmap-no-neu-cap · Review: pro Task
Spec: Kevin 2026-10-22 in der Session („Grenze ganz weg“ für den neu-Deckel); die Roadmap-Zeile trägt die Session nach dem Merge nach, weil `roadmap.py add` sie heute am Deckel (20/20) verweigert
Heavy: none — nur Harness-Skripte (roadmap.py, ein Fehlerzweig in heavy.sh) und Entwickler-Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — roadmap.py add nimmt neue Zeilen ohne Deckel an  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md, .claude/skills/roadmap/SKILL.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ae5c2e02 2026-10-22T12:11:27+02:00
Review: approve (.ah-out/review/roadmap-no-neu-cap/T1.verdict.json)
Änderung: `cmd_add` verweigert bei 20 offenen `neu`-Zeilen nicht mehr (die Prüfung, `NEU_CAP` und Exit 3 in der Usage fallen weg); die Zahl `neu N/20` im WIP-Kopf bleibt als Anzeige wie bei aktiv/bereit/pr. `roadmap_append` in heavy.sh verliert den Zweig `3) ROADMAP FULL` und den Deckel im Kommentar und im grep; heavy_test.sh 4i-c prüft stattdessen, dass bei 20 offenen `neu`-Zeilen die REG-Zeile als 21. dazukommt und der Report kein `ROADMAP FULL` nennt; test_roadmap.py prüft, dass `add` die 21. `neu`-Zeile anlegt. `.claude/skills/test/SKILL.md:56` bleibt unberührt (liegt in einem Hunk von PR #257).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Exit 3 im roadmap.py-Abschnitt, Deckel im heavy.sh-Abschnitt) · .claude/skills/roadmap/SKILL.md (Exit-Codes, WIP-Anzeige, Triage-Hinweis) · CHANGELOG (Unreleased)
Test-Löschung: scripts/dev/tests/test_roadmap.py::test_the_neu_cap_refuses_the_21st — Kevin 2026-10-22: kein neu-Deckel mehr; ersetzt durch einen Test, dass `add` die 21. neu-Zeile anlegt

### T2 — /test-Skill: kein „full `neu` cap“ mehr als Grund einer verweigerten Zeile  [x]
Komponente: scripts · Dateien: .claude/skills/test/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @68a04f90 2026-10-22T12:32:19+02:00
Review: approve (.ah-out/review/roadmap-no-neu-cap/T2.verdict.json)
Änderung: Nach dem Merge von #257 (237b450a) nennt `.claude/skills/test/SKILL.md:58` noch „a refused row — full `neu` cap, open duplicate —“; der Deckel ist mit T1 weg, verweigert wird nur noch eine offene Dublette. Die Klammer nennt nur noch diese.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (die Stelle ist selbst Doku)
