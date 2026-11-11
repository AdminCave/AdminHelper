<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-4

## Problem / Motivation
R-1212: `SettingsModal.identity.test.ts` (device identity line) und `SettingsModal.save.test.ts` (keeps the remembered
username) laufen unter Last (load 16,7 auf 8 Kernen) ins 5-s-Timeout. Kevin verlangt die Ursache der Langsamkeit, nicht
nur ein größeres Timeout.

Befund beim Planen (2026-11-11, lokal): ungestört kosten die Tests rund 0,12 s, der **erste** Test jeder Datei 0,5 s
(`valid for 2027-04-13`) bzw. der erste der Save-Datei ähnlich. Mit 24 Rechenschleifen auf 8 Kernen (load bis ~24) stieg
der erste Identity-Test auf 2,0 s und ein früher Save-Test auf 3,0 s; die übrigen blieben deutlich darunter. Der Erst-Render
des Dialogbaums ist kalt (Komponenten-Init, jsdom, JIT) und trägt unter Last den größten Teil der Zeit.

## Ziel & Nicht-Ziele
Ziel: der kalte Erst-Render fällt nicht mehr in das 5-s-Budget eines Tests, sondern in ein `beforeAll` (eigenes
`hookTimeout`, 10 s). Nicht-Ziele: globales `testTimeout` anheben (versteckt die Ursache); `vitest.setup.ts` ändern
(trifft alle Dateien).

## Betroffene Komponenten & Dateien
`apps/desktop/ui/src/components/SettingsModal.identity.test.ts`, `SettingsModal.save.test.ts` (nur Tests).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- Warm-up im `beforeAll` je Datei (Empfehlung): klein, ehrlich, ein Render mit sofortigem `cleanup()`.
- `testTimeout` je Datei anheben: verdeckt die Ursache.
- Global in `vitest.setup.ts` aufwärmen: trifft alle Dateien, Harness-nah.
Offen, ob der Warm-up den Erst-Test unter Last wirklich unter 1 s drückt: die Task misst vorher/nachher mit
derselben künstlichen Last und hält die Zahlen im Ledger fest. Zeigt die Messung keinen Effekt, geht die Frage an den
`advisor`, nicht in ein größeres Timeout.

## Risiken & Rollback
Reine Teständerung; ein Warm-up, der Zustand der Stores verändert, würde Tests beeinflussen: `cleanup()` und die
bestehenden `beforeEach`-Resets laufen danach. Rollback: Revert.

## Doku-Impact
Keine (Tests).

## Offene Fragen
Keine.
