# ops-12 — Dateien:-Zeile ohne Kommas wird abgewiesen

Roadmap: R-1646 (REF, Harness). Kevin 2026-11-19: als eigener Zug reparieren.

## Problem / Motivation

`task-close.sh --stage` liest die `Dateien:`-Zeile einer Task als kommagetrennte Liste und nimmt je Element nur das
erste Wort (`scripts/dev/task-close.sh:127`, damit `datei (neu)` als `datei` gilt). Trennt eine Zeile die Pfade mit
Leerzeichen statt Kommas, stagt das Skript nur den ersten Pfad, prüft die übrigen nicht (Restdateien, Token-Scan,
Test-Gate) und committet trotzdem: bei kern-windows-2 T1 fehlten Test und changelog im Commit
(feature/kern-windows-2@29d1b059d). `ledger.sh lint` lässt die Zeile durch.

## Ziel und Nicht-Ziele

Ziel: Ein Element der `Dateien:`-Zeile, das nach dem Entfernen der Klammer-Notizen noch Leerzeichen trägt, ist an
beiden Stellen ein Fehler: `ledger.sh lint` meldet `ERROR` (Exit 1), `task-close.sh` bricht mit Exit 2 ab (Eingabe
reparieren), wie heute schon bei `·` und `+` als Trenner.

Nicht-Ziele: kein anderes Format der Zeile; Klammer-Notizen (`datei (neu)`, `keine (eigener Zug)`) bleiben gültig.

## Betroffene Komponenten und Dateien

`scripts/dev/task-close.sh`, `scripts/dev/ledger.sh` (lint), `scripts/tests/task_close_test.sh`,
`scripts/tests/ledger_test.sh`. Harness-Pfade, auf Kevins Wort (CLAUDE.md §4).

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Keine.

## Trade-offs und Alternativen

Leerzeichen als zweiten Trenner zulassen: würde Notizen ohne Klammern (`datei neu`) still zu Pfaden machen. Der
Abbruch ist eindeutig und deckt sich mit der bestehenden `·`/`+`-Regel. Bestand auf `origin/main`: keine
`Komponente:`-Zeile hat ein solches Element außer in Klammern, lint bleibt für alle Ledger grün.

## Risiken und Rollback

Ein Ledger mit einer Notiz ohne Klammern scheitert künftig am Commit (Exit 2, Hinweis auf `set-files`). Rollback:
Revert des Task-Commits.

## Doku-Impact

`tasks/README.md` nennt das Format der `Dateien:`-Zeile; ein Halbsatz dort, dass Pfade mit Komma getrennt werden
und Notizen in Klammern stehen, sofern er fehlt.

## Offene Fragen

Keine.
