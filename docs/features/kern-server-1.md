<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Nacharbeiten an Mail, Schlüsseldatei, Hooks, CLI, Bootstrap und Gateway-Namen

Zug `kern-server-1` (Roadmap R-0827, R-0832, R-0836, R-0837, R-0839, R-0845, R-0846, R-0897, R-0901, R-0942).
Stand des Codes: `origin/main@9baee4b1`. Pfade ohne Präfix liegen unter `apps/server/`. Die Zeile R-0900 aus
diesem Zug wartet auf eine Entscheidung und fährt im nächsten Zug.

## Problem / Motivation

1. **Mail-Betreff (R-0827).** `send_email` (`app/modules/notifications/sender.py:20-29`) setzt den Betreff
   unverändert. Das Monitoring macht ihn seit monitoring-hardening-2 einzeilig (`apps/monitoring/app/alerter.py:78-80`,
   `_SUBJECT_TO_SPACE`); der Server soll dieselbe Regel haben.
2. **Rechte der Schlüsseldatei (R-0832).** `_resolve_secret_key` (`app/core/config.py:86-109`) liest eine vorhandene
   `DATA_DIR/.secret_key`, ohne ihre Rechte anzusehen; neu angelegt wird sie mit 0600 (`publish_private_file_once`).
   Beim Start soll eine Warnung erscheinen, wenn Gruppe oder andere sie lesen dürfen.
3. **HOME des Hook-Workers (R-0836).** `script_runner.py:122` fällt auf `HOME=/tmp` zurück. Der Worker bekommt
   ein eigenes Verzeichnis unter `DATA_DIR` (0700).
4. **NaN im Webhook-Body (R-0837, BUG, nicht verifiziert).** `request.json()` (`app/modules/hooks/router.py:213-216`)
   nimmt `NaN`/`Infinity` an; der Fund sagt, der Aufruf ende mit 500 statt 422.
5. **CLI-Passwort über 128 Zeichen (R-0839, BUG, nicht verifiziert).** `create-admin`/`reset-admin`
   (`app/cli.py:50-93`) prüfen nur die Mindestlänge; die API nimmt höchstens 128 Zeichen an
   (`app/modules/users/schemas.py:23`), ein längeres CLI-Passwort ließe sich dann nicht zum Login nutzen.
6. **Payload-Schreiben ohne Zeitlimit (R-0845, BUG).** `script_runner.py:204-209` schreibt den Payload vor
   `proc.wait(timeout)`; liest der Worker stdin nicht und ist der Payload größer als der Pipe-Puffer, blockiert der
   Aufruf über das Limit hinaus.
7. **Ausgabe geht verloren, wenn ein Nachfahre stdout offen hält (R-0846, BUG).** `_drain` (`:179-187`) liest in
   einem Stück bis EOF; bleibt die Pipe offen, hat der Leser nach der Gnadenfrist nichts gesammelt, der Aufruf meldet
   „Ungueltige Worker-Ausgabe“.
8. **Gateway-Namen (R-0897 REF, R-0901).** `_NameResolver` (`app/core/middleware.py:68-166`) startet seinen Thread
   erst bei der ersten Anfrage, und `_run` (`:164-166`) endet bei einer unerwarteten Ausnahme. Die Auflösung der
   Gateway- und Proxy-Namen (`app/core/identity.py:63-64`, `middleware.py:24-33`) soll nur die gemeinten
   Container-Namen treffen.
9. **Bootstrap mit mehreren Workern (R-0942, BUG).** `bootstrap` (`app/modules/users/auth_router.py:321-398`) prüft
   „kein Nutzer“ und legt dann an, ohne Sperre; zwei Worker mit gültigem Token können zwei Admins anlegen.

## Ziel & Nicht-Ziele

Ziel: je Zeile das beschriebene Verhalten, mit Test. Nicht-Ziele: neue Konfigurationsschalter, Änderungen an
API-Verträgen, Migrationen.

## Betroffene Komponenten & Dateien

Nur `server` (`apps/server/`): `app/modules/notifications/sender.py`, `app/core/config.py`,
`app/modules/hooks/script_runner.py`, `app/modules/hooks/router.py`, `app/cli.py`,
`app/modules/users/auth_router.py`, `app/core/middleware.py`, `app/core/identity.py`, `app/main.py`, dazu Tests.

## Datenmodell / API / Migrationen

Keine Migration. R-0837 ändert nur den Status eines fehlerhaften Aufrufs (422 statt 500), R-0839 eine
CLI-Meldung. Die OpenAPI-Beschreibung bleibt gleich.

## Externe Integrationen

Keine neuen. Postgres-Sperre für R-0942 wie im Bestand (`pg_advisory_xact_lock`,
`app/modules/enrollment/models.py:108`).

## Trade-offs & Alternativen

- R-0942: Transaktions-Advisory-Lock (wie Enrollment) statt `SERIALIZABLE` oder Unique-Constraint: kein Schema,
  dieselbe Form wie der Bestand. Auf SQLite (Tests) ohne Sperre; der Test fährt gegen Postgres.
- R-0845/R-0846: Schreiben und Lesen in Threads statt `communicate(timeout)`: `communicate` puffert unbegrenzt
  (Kommentar `:172-175`).

## Risiken & Rollback

Jede Task ein Commit, einzeln zurücknehmbar. Gateway-Namen (T8) berühren die Vertrauensprüfung; `security` prüft
T1–T3, T7 und T8.

## Doku-Impact

Hooks (`docs/developer/hooks.html` + EN: HOME des Workers, Ausgabe bei offenem stdout), Installation
(`docs/admin/installation.html` + EN: Warnung zur Schlüsseldatei, Gateway-/Proxy-Namen), CLI-Grenze in
`docs/admin/benutzer.html` + EN `users.html`. CHANGELOG über `changelog.d/kern-server-1.md`.

## Offene Fragen

Keine in diesem Zug; die Frage zu R-0900 steht am Gate.
