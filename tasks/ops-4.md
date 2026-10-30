<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-4 — Task-Ledger
Status: geplant · Branch: feature/ops-4 · Review: am Ende
Spec: docs/features/ops-4.md (Roadmap R-1014, R-1015)
Heavy: none — nur Bash-Filter der .env und sed-Regeln; diagnostics_test und restore_guard_test fahren sie lokal ohne Stack
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@8df222b7`, vor dem Bauen neu greppen. `security` in der Abschlussprüfung.

### T1 — diagnostics.sh: exakter dotenv-Tokenizer für env_values und sanitize_env (R-1014)  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-4.md
Änderung: Ein awk-Tokenizer nach compose-go (Spec) zerlegt die ganze `.env` in Anweisungen mit Byte-Positionen;
`env_values` (`scripts/diagnostics.sh:260`) und `sanitize_env` (`:417`) nutzen ihn, die bisherige Über-Maskierung
(allein gelesen hinter Zeilenanfang und Quote, Kommentare) bleibt. Neue Fälle: der offene Quote eines anderen
Schlüssels über Zeilen (`A="x` / `SECRET_KEY=a" SMTP_PASSWORD="c` / `leak3"`) in `env.sanitized` und in den Logs.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-4.md

### T2 — backup.sh: derselbe Tokenizer für den Passphrase-Filter (R-1014)  [ ]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, scripts/tests/diagnostics_test.sh
Änderung: Der Filter in `scripts/backup.sh:121` baut auf einer Kopie des Tokenizer-Texts aus T1; ein Test hält
beide Kopien byte-gleich. Neuer Fall: `CA_ROOT_PASSPHRASE` hinter dem über Zeilen offenen Quote eines anderen
Schlüssels fehlt in `env.sanitized` des Backups.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test diagnostics_test
Doku: keine (Verhalten wie dokumentiert, nur exakter)
Abhängt von: T1

### T3 — Masken-Reihenfolge mit Platzhalter (R-1015)  [ ]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-4.md
Änderung: `build_redaction_sedfile` (`scripts/diagnostics.sh:97`) ersetzt jeden Wert (längster zuerst) durch einen
Platzhalter aus Zeilenumbrüchen, den die Token-Regeln als Token-Byte mitlesen, dann die Token-Formen, dann
Platzhalter → `<redacted>`, dann die Host-Regeln. Neue Fälle: kurzer Wert mit Nicht-Token-Byte direkt an einem
Bearer- und einem JWT-Token, langer Wert mitten in einem Token; keine Restbytes.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-4.md

## Entscheidungen
