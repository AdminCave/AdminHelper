<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-4 — .env-Filter mit exaktem dotenv-Tokenizer, Masken-Reihenfolge

Roadmap R-1014, R-1015 (Zug `tasks/ops-4.md`).

## Problem / Motivation
- **R-1014:** `env_values` und `sanitize_env` (`scripts/diagnostics.sh:260`, `:417`) und der Passphrase-Filter
  von `scripts/backup.sh:121` lesen die `.env` Zeile für Zeile. Einen Wert in Anführungszeichen, der über Zeilen
  läuft, verfolgen sie nur für den gesuchten Schlüssel; der offene Quote eines anderen Schlüssels aus einer
  früheren Zeile geht verloren. Beispiel: `A="x` / `SECRET_KEY=a" SMTP_PASSWORD="c` / `leak3"`; compose setzt
  `SMTP_PASSWORD` auf `c\nleak3`, `env.sanitized` behält `leak3`. Dieselbe Klasse in `backup.sh` für
  `CA_ROOT_PASSPHRASE`.
- **R-1015:** `build_redaction_sedfile` (`scripts/diagnostics.sh:97`) maskiert Werte unter 8 Byte erst nach den
  Token-Regeln. Steht ein solcher Wert ohne Trenner an einer Token-Form und enthält er ein Byte außerhalb der
  Token-Klasse, nimmt die Token-Regel den Anfang, die Wert-Regel greift danach nicht mehr, Restbytes bleiben.
  Umgekehrt zerteilt ein langer Wert, der vorher zu `<redacted>` wird, ein Token, dessen Rest stehen bleibt.

## Ziel & Nicht-Ziele
- Ein Tokenizer in awk, der die ganze Datei so in Anweisungen zerlegt wie compose-go
  (`dotenv/parser.go`: `getStatementStart`, `locateKeyName`, `extractVarValue`), mit Byte-Positionen je
  Schlüssel und Wert. `env_values`, `sanitize_env` und der Filter in `backup.sh` bauen darauf.
- Die heutige Über-Maskierung bleibt (Sicherheitsnetz für Dateien, die compose ablehnt, und für Text, der nur wie
  eine Zuweisung aussieht): Anweisungen hinter jedem Zeilenanfang und jedem Quote werden zusätzlich allein
  gelesen, wie bisher; auskommentierte Zeilen ebenso. Jede bestehende Erwartung der Tests bleibt.
- Werte und Token-Formen werden auf der unveränderten Zeile gesucht und überlappende Fundstellen als ein Stück
  maskiert (`REDACT_AWK`), danach die Host-Regeln. Gebaut statt des zuerst geplanten Platzhalters, der einen Token
  hätte zerteilen können, wenn ein kurzer Wert einen Teil seines Namens trifft (Ledger `## Entscheidungen`, T3).
- Nicht: Variablen-Interpolation (`${…}`) auswerten, `.env` validieren, neue Schlüssel maskieren.

## Betroffene Komponenten & Dateien
`scripts/diagnostics.sh` (Tokenizer als awk-Text in einer Shell-Variable, `env_values`, `sanitize_env`,
`build_redaction_sedfile`), `scripts/backup.sh` (eigene Kopie desselben Tokenizer-Texts: beide Skripte werden
einzeln ausgeliefert, `install.sh` `RUNTIME_FILES`, `release.yml`), Tests `scripts/tests/diagnostics_test.sh`,
`scripts/tests/restore_guard_test.sh`.

## Datenmodell / API / Migrationen
Keine. Ausgabeform von `env.sanitized` (Bundle und Backup) bleibt; maskiert wird mehr, nicht weniger.

## Externe Integrationen
compose-go dotenv-Parser, https://github.com/compose-spec/compose-go/blob/main/dotenv/parser.go (gelesen
2026-10-30): Anweisungsanfang überspringt `unicode.IsSpace` und Kommentarzeilen; Schlüssel aus Buchstaben,
Ziffern, `_ . - [ ]`, Leerraum davor/dahinter (`isSpace`: `\t \v \f \r`, Leerzeichen, NEL, NBSP), Ende bei `=`,
`:` oder Zeilenende (geerbt); jedes andere Zeichen, ein leerer Schlüssel oder einer mit Leerzeichen ist ein
Fehler der ganzen Datei. Wert ohne Quote bis zum Zeilenende, abgeschnitten bei ` #`; mit Quote bis zum
schließenden, ein Backslash nimmt das nächste Byte mit; ohne schließenden Quote ein Fehler. Hinter dem
schließenden Quote beginnt die nächste Anweisung.

## Trade-offs & Alternativen
- Gemeinsame awk-Datei unter `scripts/lib/`: sauberer, ändert aber `install.sh` und `release.yml` (Kevin-Merge,
  Install-Pfad). Empfehlung: zwei Kopien plus Test, der sie byte-gleich hält.
- Nur exakt (ohne Über-Maskierung): einfacher, maskiert aber in einer Datei, die compose ablehnt, nichts Sicheres
  mehr und schwächt bestehende Tests. Verworfen.
- R-1015 über zwei Durchläufe (kurze Werte vor und nach den Tokens): ließe Restbytes bei Überlappung. Der
  Platzhalter (eine Folge von Zeilenumbrüchen, die in keiner Zeile stehen kann und die die Token-Klassen
  mitlesen) löst beide Richtungen.

## Risiken & Rollback
Maskierungs-Code, sicherheitsrelevant: `security` in der Abschlussprüfung. Fehler zeigen sich als Leck in
`env.sanitized` oder den Logs des Bundles; die Tests prüfen jede bisherige Form. Rollback: Revert des Merges.

## Doku-Impact
Keine Seite beschreibt die Zerlegung; `docs/admin/troubleshooting.html` (DE+EN) sagt nur, was maskiert wird, und
bleibt richtig. CHANGELOG über `changelog.d/ops-4.md`.

## Offene Fragen
Keine (Kevin 2026-10-30: Restrisiko bis zum Tokenizer hingenommen, einplanen).
