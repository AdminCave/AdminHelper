<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-5 — Spec

Roadmap: R-1026 (Zug `tasks/kern-ca-5.md`).

## Problem / Motivation
- **R-1026:** Die Neuprüfung eines offenen Benachrichtigungs-Streams (`_stream_reauth_ok`,
  `apps/server/app/modules/notifications/stream.py:45`) prüft die Client-Identität nicht in jeder Hinsicht so wie
  eine neue Anfrage (Details privat).

## Ziel & Nicht-Ziele
Ziel: Die Neuprüfung eines offenen Streams wiederholt die ganze Prüfung des Client-Zertifikats, die eine neue
Anfrage durchläuft, mit dem Stand der Vertrauensdateien zum Zeitpunkt der Neuprüfung; ein Test belegt es.

Nicht-Ziele: kein anderes Intervall (`_REAUTH_INTERVAL_SECS` bleibt), keine Änderung an Routen außerhalb des Streams.

## Betroffene Komponenten & Dateien
Nur der Server:
- `apps/server/app/core/identity.py` (`ClientIdentity`, `get_client_identity`)
- `apps/server/app/modules/notifications/stream.py` (`_stream_reauth_ok`)
- Tests: `apps/server/tests/test_stream.py`
- `docs/developer/server.html`, `docs/en/developer/server.html` (Absatz „Push (SSE)“)

## Datenmodell / API / Migrationen
Keine Migration, keine API-Änderung.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Das Zertifikat vom Connect bleibt in der Identität (ohne `repr`, ohne Vergleich), die Neuprüfung rechnet daraus neu.
Alternative: die Prüfung in `_is_revoked` für jede Anfrage wiederholen — doppelte Arbeit je Anfrage ohne Gewinn.
Empfehlung: nur der Stream rechnet neu.

## Risiken & Rollback
Gering; ein offener Stream endet früher, sobald sein Zertifikat die Prüfung nicht mehr besteht. `git revert`.

## Doku-Impact
Der Absatz „Push (SSE)“ der Server-Architektur (DE und EN) nennt, was die minütliche Neuprüfung prüft. Der
Changelog-Eintrag ist neutral.

## Offene Fragen
Keine.
