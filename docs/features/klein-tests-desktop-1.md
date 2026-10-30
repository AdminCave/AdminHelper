<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-1 — Desktop-Test-Lücken

Roadmap R-0903, R-0886. Beide Zeilen ändern nur Tests; keine Überlappung mit einem offenen Branch
(`overlap.sh` ohne Treffer für `launcher.rs`, `settings.test.ts`, `session.ts`).

## Problem / Motivation
- **R-0903:** `launcher::tests::open_fails_at_once_when_the_workspace_ends_before_it_holds_its_lock` pinnt „kein
  Warten bis zur Frist" mit einer Frist von 900 ms und `waited < timeout`. Auf dem Windows-Runner dauerte der Lauf
  1,41 s (Scheduling), der Test fiel auf `main` rot. Die Zusicherung ist zeitabhängig knapp.
- **R-0886:** `settings.test.ts` mockt `$lib/bridge` ohne `workspaceContext`. `session.hydrate()` loggt in den
  Logout-Tests `workspace context failed` und läuft am Workspace-Zweig vorbei; die Tests prüfen damit nicht den
  Pfad, den die App fährt.

## Ziel & Nicht-Ziele
- R-0903: die Frist so groß, dass Jitter sie nicht reißt, der Test aber weiter rot wird, wenn `open_within` bis zur
  Frist wartet.
- R-0886: `workspaceContext` im Mock (Server-Workspace), und ein unerwartetes `console.error` lässt den Test fallen.
- Nicht-Ziel: Änderungen an `launcher.rs`-Produktivcode oder an `session.ts`.

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/launcher.rs` (Testmodul), `apps/desktop/ui/src/lib/stores/settings.test.ts`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
R-0903: statt der Frist die Messung zu entfernen, bleibt die Zusicherung („weit unter der Frist"), nur mit
10 s Frist; ein hängender `open_within` kostet im Fehlerfall 10 s, nicht mehr. Empfehlung: Frist anheben.

## Risiken & Rollback
Reine Teständerungen; Rollback per Revert.

## Doku-Impact
Keine (nur Tests).

## Offene Fragen
Keine.
