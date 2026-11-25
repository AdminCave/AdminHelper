<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Weckbedingung für zurückgestellte Roadmap-Zeilen — Task-Ledger
Status: geplant · Branch: feature/kern-roadmap-1 · Review: am Ende
Spec: Roadmap R-1780
Heavy: none — nur `scripts/dev/roadmap.py` samt Unit-Tests und Markdown (Skill, DEVELOPMENT.md, ein Ledger-Kopf); kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-11-25: „ja mache 1bis 3 du mergst dann und gehe auch alles einmal durch und räme ggf auf“. Gemeint sind
(1) eine prüfbare Weckbedingung beim Zurückstellen, (2) eine Meldung „Wieder fällig“, sobald sie erfüllt ist, ohne
automatischen Statuswechsel, und (3) eine einmalige Durchsicht der zurückgestellten Zeilen. (3) läuft über
`roadmap.py` in der privaten Roadmap und ist keine Task hier. Anlass: R-1636 (Monitoring P1b) stand zurückgestellt,
ohne dass irgendetwas meldete, dass seine Voraussetzung längst gemergt war.

### T1 — roadmap.py: `status … zurückgestellt --until`, „Wieder fällig“, Lint ohne Bedingung  [ ]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py
Änderung: `status` nimmt `--until R-nnnn|JJJJ-MM-TT` (mehrfach). Die Weckbedingung steht in der Spalte „Hängt ab von“:
R-IDs wie bisher, ein Datum als `ab JJJJ-MM-TT`. `prune` hält eine dort genannte geschlossene Zeile schon im Archiv,
und `next` liest nur die R-IDs. Der Wechsel nach `zurückgestellt` verlangt eine Weckbedingung (`--until` oder eine
schon vorhandene), sonst Exit 2. `--until` gilt nur für `zurückgestellt`; eine unbekannte R-ID oder ein Datum, das
nicht nach heute liegt, ist Exit 2. „Als Nächstes“ (und damit der AH-STATUS, der dessen Punkte druckt) bekommt einen
Punkt „Wieder fällig: R-x (R-y abgeschlossen) · …“ für jede zurückgestellte Zeile, deren R-IDs alle geschlossen sind
und deren Datum erreicht ist. Der Status bleibt, die Entscheidung trifft Kevin. `lint` meldet eine zurückgestellte
Zeile ohne Weckbedingung. Bestehende Tests, die ohne Bedingung zurückstellen, bekommen `--until`: gewollte
Verhaltensänderung, gleiche Prüfung.
Verify: bash scripts/dev/verify.sh scripts --strict -- scripts/dev/tests/test_roadmap.py
Doku: → T2

### T2 — Doku: Skill und DEVELOPMENT.md; Ledger-Kopf kern-config-1  [ ]
Komponente: scripts · Dateien: .claude/skills/roadmap/SKILL.md, DEVELOPMENT.md, tasks/kern-config-1.md
Änderung: Der roadmap-Skill nennt beim Zurückstellen `--until` und die Meldung „Wieder fällig“; DEVELOPMENT.md
beschreibt `--until`, die Spalte und den neuen Lint-Fund im Abschnitt `status`. Aufräumen: `tasks/kern-config-1.md`
steht auf `main` noch auf `Status: bereit` (T7 kam nach „erledigt“), deshalb zeigt der AH-STATUS den Zug als laufend;
der Kopf wird `erledigt`.
Verify: bash scripts/dev/verify.sh scripts --strict -- scripts/dev/tests/test_roadmap.py
Doku: diese Task
Task-Review: am Ende
Abhängt von: T1

## Entscheidungen
