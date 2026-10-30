<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: unlesbare Idle-Zeit, Refresh ohne Web Locks, Pflichtfelder im Vertragstest

Zug `kern-web-3` (Roadmap R-0989, R-0975, R-0980). Stand des Codes: `origin/main@66d3ef6f`.

## Problem / Motivation

1. **Unlesbare Idle-Zeit (R-0989, BUG).** `watchIdle` (`apps/web/src/lib/idle.ts:35-42`) rechnet beim Laden
   `age = Date.now() - Number(stored)`. Steht unter `adminhelper_last_activity` kein Zahlwert, ist `age` `NaN`, beide
   Vergleiche sind falsch, und die Sitzung bleibt, obwohl ihr Alter unbekannt ist. Eine Zeit nach der Uhr beendet
   die Sitzung heute schon (R-0890, Kevins Wort: unbekanntes Alter heißt abmelden).
2. **Refresh ohne Web Locks (R-0975, REF).** `withAuthLock` (`apps/web/src/lib/api/client.ts:88-93`) ruft `fn`
   ohne Web Locks (kein sicherer Kontext) sofort auf. `tryRefresh` bündelt nur je Sitzung (`refreshInFlight`), also
   können im selben Tab ein Refresh der alten und einer der neuen Sitzung gleichzeitig laufen. Fail-safe (der
   Server beendet dann die Sitzungen), aber unnötig.
3. **Pflichtfelder in Anfragen (R-0980, REF).** `compare()` im Vertragstest (`apps/web/src/lib/api/types.contract.test.ts:285`,
   gleich in `apps/desktop/ui/src/lib/api/types.contract.test.ts`) meldet nur bei Antworten fehlende Schema-Felder.
   Fehlt einem Anfrage-Typ ein Pflichtfeld des Schemas, bleibt der Test grün.

## Ziel & Nicht-Ziele

- Ziel: Eine gespeicherte Zeit, die keine endliche Zahl ist, beendet die Sitzung beim Laden wie eine Zeit nach der
  Uhr; eine fehlende (`null`) weiter nicht.
- Ziel: Ohne Web Locks laufen die Aufrufe von `withAuthLock` im Tab nacheinander (eine Promise-Kette im Modul).
- Ziel: `compare()` meldet bei `request` jedes Pflichtfeld des Schemas, das der TS-Typ nicht trägt und `omit` nicht
  nennt; gefundene Lücken werden im Typ geschlossen oder mit Grund in `omit` aufgenommen.
- Nicht-Ziel: tabübergreifender Ersatz für Web Locks (ohne sicheren Kontext gibt es keinen; der Server-Schutz
  bleibt).
- Nicht-Ziel: ein gemeinsames Vertragstest-Modul für Web und Desktop.

## Betroffene Komponenten & Dateien

Web: `idle.ts` + `idle.test.ts`, `api/client.ts` + `api/client.crosstab.test.ts`, `api/types.contract.test.ts`.
Desktop-UI: `api/types.contract.test.ts`. Keine API-, Schema- oder Migrationsänderung.

## Externe Integrationen

Keine (Web Locks API wie bisher, nur der Fall ohne sie).

## Trade-offs & Alternativen

- R-0975: eine Promise-Kette ist die kleinste Lösung; ein Mutex-Paket wäre YAGNI. Reentranz bleibt wie bei Web
  Locks verboten (Kommentar steht schon).

## Risiken & Rollback

R-0989 meldet ab, wo heute eine Sitzung blieb: nur bei einem unlesbaren Wert, den die App selbst nie schreibt.
Jede Task einzeln revertierbar.

## Doku-Impact

`docs/admin/benutzer.html` + EN: der Satz zur Abmeldung beim Laden nennt auch eine unlesbare gespeicherte Zeit.
CHANGELOG über `changelog.d/kern-web-3.md`. R-0975: Entwicklerseite webui.html (Fall ohne Web Locks); R-0980: Regeln des Vertragstests in cicd.html (DE+EN).

## Offene Fragen

Keine.
