<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-6 — Spec

Roadmap: R-1059 (Zug `tasks/kern-server-6.md`).

## Problem / Motivation
- **R-1059:** Ein offener Benachrichtigungs-Stream (`GET /api/notifications/stream`) prüft seine Anmeldung etwa
  einmal pro Minute neu (`_stream_reauth_ok`, `apps/server/app/modules/notifications/stream.py:45`): das Bearer-JWT,
  den Widerruf des mTLS-Zertifikats und die Vertrauensdatei. Das Ende der Gültigkeit des Zertifikats (`not_after`)
  prüft sie nicht. Läuft das Zertifikat ab, während der Stream offen ist, bleibt er bis zum Ablauf des JWT offen.
  `ClientIdentity` trägt `not_after` schon (`apps/server/app/core/identity.py:101`).

R-1056 (Regel für Servernamen) fährt nicht mit: Die Antwort ändert den API-Vertrag und liegt bei Kevin; die Zeile
wartet mit der Frage im Zug `tasks/kern-server-7.md`.

## Ziel & Nicht-Ziele
Ziel: Die Neuprüfung beendet den Stream, sobald das verifizierte Zertifikat abgelaufen ist, belegt durch einen Test.

Nicht-Ziele:
- kein Timer auf genau `not_after`: der Stream endet bei der nächsten Neuprüfung (höchstens etwa eine Minute später),
  wie bei Widerruf und Vertrauensdatei;
- keine Änderung für nicht verifizierte Identitäten (ohne Zertifikat gibt es kein `not_after`);
- keine Änderung am Connect: dort prüft schon der TLS-Handshake die Gültigkeit.

## Betroffene Komponenten & Dateien
Nur der Server und seine Entwickler-Doku:
- `apps/server/app/modules/notifications/stream.py`
- `apps/server/tests/test_stream.py`
- `docs/developer/server.html`, `docs/en/developer/server.html`
- `changelog.d/kern-server-6.md`

## Datenmodell / API / Migrationen
Keine. Kein neues Feld, keine Migration; die Route antwortet wie bisher, der Stream endet nur früher.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- **Vergleich in `_stream_reauth_ok` (empfohlen):** eine Bedingung neben dem Widerruf, naive UTC wie
  `not_after` (F7); kein neuer Pfad.
- Vergleich im Generator `gen()`: trennte die Prüfung von den übrigen und bräuchte einen eigenen Test-Weg.

## Risiken & Rollback
- Uhrzeit: Der Vergleich nutzt naive UTC wie `not_after`; eine aware/naive-Mischung wäre ein `TypeError` und damit
  ein abgebrochener Stream (fail-closed). Der Test deckt beide Seiten der Grenze.
- Rollback: `git revert` des Task-Commits, keine Daten.

## Doku-Impact
`docs/developer/server.html` und `docs/en/developer/server.html` (Absatz „Push (SSE)“): die Neuprüfung nennt den
Ablauf des Zertifikats; dazu ein Changelog-Fragment.

## Offene Fragen
Keine.
