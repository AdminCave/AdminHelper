<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-4 — Task-Ledger
Status: bereit · Branch: feature/ops-4 · Review: am Ende
Spec: docs/features/ops-4.md (Roadmap R-1014, R-1015)
Heavy: none — nur Bash-Filter der .env und sed-Regeln; diagnostics_test und restore_guard_test fahren sie lokal ohne Stack
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@8df222b7`, vor dem Bauen neu greppen. `security` in der Abschlussprüfung.

### T1 — diagnostics.sh: exakter dotenv-Tokenizer für env_values und sanitize_env (R-1014)  [x]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-4.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @08d1cfdc 2026-10-30T18:45:20+01:00
Review: am Ende (Branch-Review)
Änderung: Ein awk-Tokenizer nach compose-go (Spec) zerlegt die ganze `.env` in Anweisungen mit Byte-Positionen;
`env_values` (`scripts/diagnostics.sh:260`) und `sanitize_env` (`:417`) nutzen ihn, die bisherige Über-Maskierung
(allein gelesen hinter Zeilenanfang und Quote, Kommentare) bleibt. Neue Fälle: der offene Quote eines anderen
Schlüssels über Zeilen (`A="x` / `SECRET_KEY=a" SMTP_PASSWORD="c` / `leak3"`) in `env.sanitized` und in den Logs.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-4.md

### T2 — backup.sh: derselbe Tokenizer für den Passphrase-Filter (R-1014)  [x]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, scripts/tests/diagnostics_test.sh, scripts/diagnostics.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1365c461 2026-10-30T18:53:17+01:00
Review: am Ende (Branch-Review)
Änderung: Der Filter in `scripts/backup.sh:121` baut auf einer Kopie des Tokenizer-Texts aus T1; ein Test hält
beide Kopien byte-gleich. Neuer Fall: `CA_ROOT_PASSPHRASE` hinter dem über Zeilen offenen Quote eines anderen
Schlüssels fehlt in `env.sanitized` des Backups.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test diagnostics_test
Doku: keine (Verhalten wie dokumentiert, nur exakter)
Abhängt von: T1

### T3 — Masken-Reihenfolge mit Platzhalter (R-1015)  [x]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-4.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @34cea667 2026-10-30T19:06:47+01:00
Review: am Ende (Branch-Review)
Änderung: `build_redaction_sedfile` (`scripts/diagnostics.sh:97`) ersetzt jeden Wert (längster zuerst) durch einen
Platzhalter aus Zeilenumbrüchen, den die Token-Regeln als Token-Byte mitlesen, dann die Token-Formen, dann
Platzhalter → `<redacted>`, dann die Host-Regeln. Neue Fälle: kurzer Wert mit Nicht-Token-Byte direkt an einem
Bearer- und einem JWT-Token, langer Wert mitten in einem Token; keine Restbytes.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: changelog.d/ops-4.md

### T4 — REDACT_AWK linear in den Fundstellen einer Zeile (R-1015, Abschlussprüfung)  [x]
Komponente: scripts · Dateien: scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b7fa1854 2026-10-30T19:33:40+01:00
Review: am Ende (Branch-Review)
Änderung: `REDACT_AWK` (`scripts/diagnostics.sh:408`) sucht die Token-Formen in einem Durchgang je Regel und wählt die
Läufe über die Startstellen statt je Lauf über alle Fundstellen; die Laufzeit wächst nicht mehr quadratisch mit Log-Text
voller Token-Formen. Neuer Fall: eine lange Zeile mit vielen Query-Tokens in einer Zeitgrenze.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: keine (Laufzeit, kein Verhalten)
Abhängt von: T3

## Entscheidungen
- T1: Tokenizer = exakter Lauf nach compose-go ∪ der bisherige Lauf „allein gelesen“ an jedem Zeilenanfang und hinter
  jedem Quote (maskiert nie weniger als vorher); einen Schlüssel, den compose ablehnt, überspringt der exakte Lauf bis
  zum Zeilenende. Zwei Kopien des awk-Texts (diagnostics.sh, backup.sh) statt `scripts/lib/`: sonst ändern sich
  install.sh und release.yml. Fall (q) ist mit der alten Fassung in `sanitize_env` rot, der Log-Teil war schon grün
  (env_values verfolgte den gesuchten Schlüssel hinter jedem Quote) und bleibt als Schutz.
- T2: backup.sh trägt den Block zwischen `# >>> dotenv tokenizer` und `# <<< dotenv tokenizer` samt ENV_WS/ENV_SP/ENV_SEP (dafür aus dem Kopf von diagnostics.sh in den Block verschoben); (r) vergleicht beide Blöcke. Eine auskommentierte Zeile, die ein Passphrase-Span berührt, geht ganz (wie bisher bei Kommentarzeilen); 15c ist mit der alten Fassung rot (`pp8c'` blieb).
- T3: statt des Platzhalters der Spec (Werte zuerst durch eine Folge von Zeilenumbrüchen ersetzen) maskiert ein
  awk-Lauf (`REDACT_AWK`) die Vereinigung aller Fundstellen von Werten und Token-Formen auf der unveränderten Zeile;
  der Platzhalter hätte einen kurzen Wert, der einen Teil eines Token-Namens trifft (`admin` vor
  `adminhelper_prov_`), den Token zerteilen und stehen lassen. Die Werte stehen als sed-Kommentare `#=<key> <value>`
  in der Regeldatei (nie in Argumenten), die Host-Regeln bleiben sed dahinter. Ein Token behält seinen Namen nur,
  wenn kein Wert ihn schneidet; `Bearer eyJ…` wird jetzt `Bearer <redacted>` statt `Bearer <redacted-jwt>`. (p)
  stubbt statt des Heredoc-`cat` (gibt es nicht mehr) das `sort`, das die Regeldatei ordnet; dieselbe Aussage.
- T4: jede Token-Form in einem gsub/split-Durchgang je Zeile (Marke `\n`, die eine Zeile nie trägt), die Läufe
  über die Startstellen in Byte-Reihenfolge statt je Lauf über alle Fundstellen, die Ausgabe per printf statt
  wachsender Verkettung. Gemessen mit 8000 Query-Tokens in einer Zeile: 0,14 s (gawk) bzw. 0,07 s (mawk) statt über
  10 s; (t) ist mit der T3-Fassung rot (Exit 124).
