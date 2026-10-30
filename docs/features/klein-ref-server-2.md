<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-2 — Server: UserMe-Konfiguration und Test des ADMIN_PASSWORD-Admins

Roadmap R-0869. Kein sichtbares Verhalten. `overlap.sh` auf `apps/server/app/modules/users/schemas.py` ohne Treffer
(`kern-server-1` ist gemergt).

## Problem / Motivation
- `UserMe` (`apps/server/app/modules/users/schemas.py`) trägt `model_config = {"from_attributes": True}`, aber `GET
  /api/auth/me` baut die Antwort mit `UserMe(...)` aus Einzelwerten; kein Aufrufer validiert ein ORM-Objekt. Die
  Konfiguration ist tot.
- Der Admin aus `ADMIN_PASSWORD` (`_ensure_admin` in `apps/server/app/main.py`) bekommt sein Token-Wasserzeichen
  (`users.tokens_valid_after`) nur über den Spalten-Default; die Tests decken die API-, CLI- und Bootstrap-Wege ab
  (`test_user_token_watermark.py`), diesen Weg nicht. Der Fund nannte einen eigenen „ENV-Admin-Pfad“ im Token-Check;
  den gibt es seit den uid-Tokens nicht mehr, der Admin ist eine normale `users`-Zeile.

## Ziel & Nicht-Ziele
- Die tote Konfiguration entfällt; ein Test zeigt, dass der Admin aus `ADMIN_PASSWORD` Token ab dem Start seiner
  Sekunde hält und frühere nicht.
- Nicht-Ziel: Änderung des Wasserzeichens oder des Antwortschemas (der OpenAPI-Snapshot bleibt gleich).

## Betroffene Komponenten & Dateien
`apps/server/app/modules/users/schemas.py`, `apps/server/tests/test_user_token_watermark.py`.

## Datenmodell / API / Migrationen
Keine; der OpenAPI-Snapshot wird mitgefahren (`from_attributes` steht nicht im Schema).

## Trade-offs
Der Test fährt `_ensure_admin` gegen `db_session` wie `test_env_admin_gets_default_subscription` und prüft über
`_get_user_from_token` statt über HTTP: dieselbe Entscheidung, weniger Aufbau.

## Risiken & Rollback
Gering; `git revert`.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
