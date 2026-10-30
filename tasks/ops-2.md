<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-2 — Task-Ledger
Status: aktiv · Branch: feature/ops-2 · Review: pro Task
Spec: docs/features/ops-2.md (Roadmap R-0908, R-0910, R-0909)
Heavy: none — nur Ops-Skripte mit hermetischen Tests (Docker-Stub), kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@76f331f0`, vor dem Schreiben neu greppen. Neue Code-Strings englisch,
CHANGELOG umlautfrei und neutral in `changelog.d/ops-2.md`. `security` zusätzlich bei T1, T2 und T3 (SEC).
Einzelheiten der Fälle in der privaten Spec.

### T1 — diagnostics.sh liest .env-Zeilen wie compose (R-0908)  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-2.md
Änderung: `env_values` (`diagnostics.sh:229-291`) und `sanitize_env` (`:314-358`) erkennen jede Zuweisung eines
Schlüssels, die compose aus einer Zeile liest (`compose-go/dotenv/parser.go`), auch auskommentierte Werte über mehrere
Zeilen. Tests zuerst rot: je Zeilenform ein Fall in `diagnostics_test.sh` (Masken-Regel und `env.sanitized`).
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-2.md (docs/admin/troubleshooting.html nennt die Lesart der .env nicht)

### T2 — backup.sh-Filter liest .env-Zeilen wie compose (R-0908)  [ ]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, changelog.d/ops-2.md
Änderung: der Filter in `backup.sh:103-143` entfernt die gefilterte Zuweisung in jeder Form, die compose liest, und
behält andere Zuweisungen derselben Zeile; auskommentierte Werte über mehrere Zeilen gehen ganz. Ein Fehler bricht
weiter ab. Tests zuerst rot: Fälle in `restore_guard_test.sh` neben 12–14 (`env.sanitized`).
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: changelog.d/ops-2.md

### T3 — Reihenfolge der Masken-Regeln (R-0910)  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-2.md
Änderung: `build_redaction_sedfile` (`:88-127`) schreibt die Regeln der `.env`-Werte ab 8 Zeichen zuerst, dann die
allgemeinen Token-Regeln, dann die kürzeren Werte. Test zuerst rot: ein kurzer Wert in der `.env` und ein Token in
einem Log; das Token ist ganz maskiert, der kurze Wert auch.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-2.md
Abhängt von: T1

### T4 — Fehler der Masken-Programme brechen ab (R-0909)  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-2.md
Änderung: `env_values` schluckt die Fehlerausgabe nicht mehr (`:291`), und `build_redaction_sedfile` prüft den
Exit-Status der Wertliste (heute in einer Prozess-Substitution, `:104-118`); scheitert ein Masken-Programm, endet
`diagnostics.sh` mit Meldung, ohne Bundle. Test zuerst rot: ein scheiterndes awk (Stub im PATH) bricht ab.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-2.md
Abhängt von: T3

## Entscheidungen
- T3: keine Mindestlänge für Wert-Regeln (ließe kurze Secrets im Klartext), sondern eine dritte Gruppe nach den
  Token-Regeln. Grenze 8: zufällig mitten in einem Token steht nur ein kurzer Wert; 8 liegt über der Segmentlänge 6
  der JWT-Regel, ein langer Wert läuft weiter zuerst (ein Token, das ihn enthält, verliert sonst nur einen Teil).
