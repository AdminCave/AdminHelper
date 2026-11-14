<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-4

## Problem / Motivation
R-1379 (Nit aus `klein-ui-desktop-3`): Das Desktop-Dashboard lädt im Server-Modus Server und Monitoring und zeigt die
Karten „Server“ und „Probleme“ sowie das Panel „Monitoring“ auch einem Nicht-Admin. Der Proxy antwortet ihm mit 403,
das Panel zeigt dann einen Fehler, und `openServer` führt nach `/monitoring`, das für Nicht-Admins auf das Dashboard
zurückfällt. Die Navigation blendet den Monitoring-Eintrag schon aus (`adminOnly`, `AppShell.svelte:135`).

## Ziel & Nicht-Ziele
Ziel: Für einen Nicht-Admin lädt das Dashboard weder Server noch Monitoring und zeigt weder die Karten „Server“ und
„Probleme“ noch das Panel „Monitoring“ (mit `openServer`). Der Tunnel und die Verbindungen bleiben unverändert.
Nicht-Ziele: andere Seiten, die Navigation, die API.

## Betroffene Komponenten & Dateien
`apps/desktop/ui/src/pages/Dashboard.svelte`, Tests `Dashboard.layout.test.ts`, `Dashboard.load.test.ts`.

## Datenmodell / API / Migrationen
Keine. Gleiches Muster wie die Navigation: `$sessionStore.session?.isAdmin === true`.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Die Karten „Server“ und „Probleme“ stehen auf denselben Monitoring-Daten und zeigen einem Nicht-Admin sonst 0 und „-“
(es sähe nach einem leeren Monitoring aus); sie fallen deshalb mit weg, nicht nur das Panel. Die Zeile nennt nur das
Panel und `openServer`; die Karten sind dieselbe Ursache. Empfehlung: umgesetzt wie beschrieben.

## Risiken & Rollback
Sichtbares Verhalten nur für Nicht-Admins im Server-Modus; Revert der einen Task.

## Doku-Impact
Keine (die Doku nennt Monitoring als Admin-Funktion; `grep` vor dem Abschluss).

## Offene Fragen
Keine.
