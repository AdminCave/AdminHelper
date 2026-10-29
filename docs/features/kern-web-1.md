<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Web: Sitzungsgrenzen im API-Client

Zug `kern-web-1` (Roadmap R-0923, R-0924). Stand des Codes: `origin/main@2489bfc4`. Pfade ohne Präfix liegen unter
`apps/web/src/lib/`.

## Problem / Motivation

1. **Refresh über eine Sitzungsgrenze (R-0923, BUG).** `tryRefresh` (`api/client.ts:95`) bündelt alle 401 in einem
   `refreshInFlight`, ohne die Sitzung zu prüfen. Startet ein Refresh vor dem Abmelden und antwortet er nach der
   neuen Anmeldung, liefert er `false` (`started !== session`, `api/client.ts:111`). Ein 401 der neuen Sitzung, der
   sich in dieser Zeit an dasselbe Promise hängt, ruft dann `onAuthFailure` und beendet die neue Sitzung. Nur ohne
   Web Locks und nur, wenn ein frisches Token sofort 401 bekommt.
2. **Anmeldung bei gehaltenem Token (R-0924, BUG).** `setAccessToken` (`api/client.ts:56`) beginnt eine neue Sitzung
   nur, wenn kein Token gehalten wird. Scheitert `auth.hydrate()` nach einem erfolgreichen Restore an `/me` ohne
   401/403, setzt `stores/auth.ts:68` `user: null`, ohne `clearTokens()`; eine danach folgende Anmeldung eines
   anderen Benutzers bekommt keine neue Sitzungs-Generation. Heute nicht ausnutzbar (keine Anfrage der alten Sitzung
   außerhalb `/auth/`), aber die Invariante „eine Anmeldung ist eine neue Sitzung“ gilt nicht.

## Ziel & Nicht-Ziele

Ziel: ein `refreshInFlight` gilt nur für die Sitzung, in der er startete; jede Anmeldung beginnt eine neue Sitzung.
Nicht-Ziele: Server, Desktop, Idle-Abmeldung (R-0890 fährt im nächsten Zug, Frage an Kevin).

## Betroffene Komponenten & Dateien

`web`: `api/client.ts`, `api/auth.ts`, Test `api/client.test.ts`.

## Datenmodell / API / Migrationen

Keine. Kein Aufruf am Server ändert sich.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- R-0923: `refreshInFlight` merkt sich die Sitzung, in der er startete; ein 401 einer anderen Sitzung startet einen
  eigenen Refresh. Alternative: das gebündelte Ergebnis im 401-Pfad gegen die Sitzung prüfen — verworfen, ein
  `false` der alten Sitzung sagt über die neue nichts, der eigene Refresh schon.
- R-0924: `login()` (`api/auth.ts:8`) beginnt die Sitzung ausdrücklich (`startSession`), statt sich auf „kein Token
  gehalten“ zu verlassen; `setAccessToken` behält seine Form für die übrigen Aufrufer. Alternative:
  `hydrate()` ruft im Fehlerzweig `clearTokens()` — verworfen, es deckte nur diesen einen Weg ab.

## Risiken & Rollback

Eine Task, ein Commit, einzeln zurücknehmbar. Die Sitzungslogik ist sicherheitsnah (Abmeldung, Refresh-Reuse,
R-0649): `security` prüft die Task mit.

## Doku-Impact

`changelog.d/kern-web-1.md`. Keine Seite unter `docs/` beschreibt die Sitzungs-Generationen des Web-Clients.

## Offene Fragen

Keine für diesen Zug. R-0890 (Zeitstempel aus der Zukunft beim Laden): abmelden oder nicht — Frage an Kevin, die
Zeile fährt in `kern-web-2`.
