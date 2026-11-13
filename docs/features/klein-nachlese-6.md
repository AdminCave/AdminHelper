<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-6

## Problem / Motivation
R-1431 (Nachlese klein-nachlese-4, ein Nit des Pruefers): `apps/desktop/e2e/test/specs/monitoring-server-page.live.js:55` ruft `makeShot("server-page", 5000)`. Die Theme-Umschaltung wartet dort nur 5 s, `.claude/rules/testing.md` (Fristen) verlangt mindestens 30 s. Die Frist war schon vor dem Umzug der Helfer in `monitoring-live.js` so und wurde bewusst unveraendert uebernommen; als Parameter laesst sie sich jetzt einzeln heben.

## Ziel & Nicht-Ziele
Ziel: die Frist auf 30000 ms heben, wie sie `monitoring-services.live.js` schon hat. Nicht-Ziel: weitere Aenderung an den Specs oder am Helfer.

## Betroffene Komponenten & Dateien
`apps/desktop/e2e/test/specs/monitoring-server-page.live.js` (eine Zahl).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Eine Konstante `WAIT` in der Spec einzufuehren waere mehr Aenderung als die Zahl; die Datei nennt ihre anderen Fristen als Literale oder `REFRESH_WAIT`. Empfehlung: die Zahl.

## Risiken & Rollback
Eine laengere Obergrenze verlaengert nur den Fehlerfall. Rollback: Revert des Commits.

## Doku-Impact
Keine (Testcode).

## Offene Fragen
Keine.
