<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Ops-Skripte: .env-Filter wie compose, Reihenfolge der Masken-Regeln, Fehler der Masken-Programme

Zug `ops-2` (Roadmap R-0908, R-0910, R-0909). Stand des Codes: `origin/main@76f331f0`.

## Problem / Motivation

1. **.env lesen wie compose (R-0908).** `scripts/diagnostics.sh` (`env_values`, `:229-292`; `sanitize_env`,
   `:314-358`) und der `CA_ROOT_PASSPHRASE`-Filter in `scripts/backup.sh` (`:103-143`) lesen manche Zeilenformen der
   `.env` anders als compose (`compose-go/dotenv/parser.go`). Einzelheiten privat.
2. **Reihenfolge der Masken-Regeln (R-0910).** `build_redaction_sedfile` (`diagnostics.sh:88-127`) schreibt die Regeln
   der `.env`-Werte vor die allgemeinen Token-Regeln (JWT, Bearer, Query-Token, Hook-Token, Provisionierungs-Token).
   Einzelheiten privat.
3. **Fehler der Masken-Programme (R-0909).** `env_values` leitet die Fehlerausgabe seines awk-Programms nach
   `/dev/null` (`:291`), und sein Ergebnis läuft durch eine Prozess-Substitution (`:104-118`): ein Fehler des Programms
   lässt Regeln weg, ohne Meldung und ohne Abbruch.

## Ziel & Nicht-Ziele

- Ziel: `env_values`, `sanitize_env` und der Filter in `backup.sh` erkennen jede Zuweisung, die compose aus einer Zeile
  liest; auch auskommentierte Werte über mehrere Zeilen sind ganz maskiert bzw. entfernt. Andere Schlüssel bleiben in
  `backup.sh` erhalten.
- Ziel: Allgemeine Token-Formen werden nicht von kurzen `.env`-Werten zerteilt, bevor ihre Regel greift; jeder
  `.env`-Wert bleibt maskiert.
- Ziel: Scheitert ein Masken-Programm, bricht `diagnostics.sh` mit Meldung ab, statt ein Bundle mit fehlenden Regeln zu
  schreiben (wie `backup.sh` bei einem awk-Fehler).
- Nicht-Ziel: ein vollständiger dotenv-Parser für alle Schlüssel (die Filter verfolgen weiter nur die
  Anführungszeichen der eigenen Schlüssel, `env_values`-Kommentar); keine Änderung an `compose.yml`, Logs oder
  `--mask-hosts`.

## Betroffene Komponenten & Dateien

Ops-Skripte: `scripts/diagnostics.sh`, `scripts/backup.sh`; Tests `scripts/tests/diagnostics_test.sh`,
`scripts/tests/restore_guard_test.sh` (hermetisch, Docker-Stub). Keine API-, Schema- oder Migrationsänderung.

## Externe Integrationen

compose `.env`-Parser: <https://github.com/compose-spec/compose-go/blob/main/dotenv/parser.go> (`parse`,
`getStatementStart`, `extractVarValue`), gelesen 2026-10-30.

## Trade-offs & Alternativen

- R-0910: eine Mindestlänge für Wert-Regeln ließe kurze Secrets im Klartext; nur die Token-Regeln vorziehen könnte
  einen langen Wert anschneiden. Gewählt: lange Werte zuerst (wie heute), dann die Token-Regeln, dann die kurzen
  Werte. Kein Wert bleibt unmaskiert; zufällig in einem Token stehen nur kurze Werte. Grenze 8 Zeichen (über der
  Segmentlänge 6 der JWT-Regel), Einzelheiten privat.
- R-0909: Abbruch statt Warnung; ein Diagnose-Bundle ohne verlässliche Maskierung soll nicht entstehen.

## Risiken & Rollback

Gering; jede Task ist ein eigener Commit. Eine zu weite Erkennung maskiert mehr als nötig (kein Leck), ein Abbruch
kostet ein Bundle (Meldung nennt den Grund).

## Doku-Impact

`docs/admin/troubleshooting.html` DE+EN nennt die maskierten Arten, nicht die Lesart der `.env`: keine Änderung.
CHANGELOG über `changelog.d/ops-2.md`, neutral.

## Offene Fragen

Keine.
