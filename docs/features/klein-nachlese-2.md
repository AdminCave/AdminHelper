<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-2 — Spec

## Problem
- **R-1250** (Nits aus den Prüfungen von arch-namen, R-1210):
  1. `GET /api/frp/server-config/{id}` (`apps/server/app/modules/frp/config_router.py`, `get_server_config`) liest
     `target_server` je Tunnel lazy (`FrpTunnel.display_name()`, `models.py`), Liste und Status laden es mit
     `selectinload`: eine Abfrage je Tunnel.
  2. `FrpTunnelCreate.name` und `FrpTunnelUpdate.name` (`frp/schemas.py`) haben kein `max_length`, `label` hat 255.
  3. `visitor-port` in `scripts/tests/e2e_api.py` (liest `label`, sonst `name`) hat keinen Unit-Test.
  4. Der Kommentar vor `_refused_warned` in `frp/config_generator.py` ist mitten im Absatz umgebrochen.
  5. `ConnectionEditor.svelte`: ohne geladene Serverliste zeigt der Editor bei einer Server-Verbindung das freie
     Namensfeld mit dem Anzeigenamen. **Fährt nicht mit**: wie der Editor dort aussehen soll, ist sichtbares
     Verhalten (Kevins Bereich); eigene Zeile mit Frage.

## Ziel / Nicht-Ziele
Punkte 1–4, je mit Test, wo es Verhalten ist. `name` bekommt `max_length=255` wie `label`; kein anderes Schema ändert
sich. Kein Produktcode für Punkt 3 und 4.

## Dateien
`apps/server/app/modules/frp/config_router.py`, `frp/schemas.py`, `frp/config_generator.py`,
`apps/server/tests/test_frp_tunnels.py` (neue Tests), `apps/server/tests/openapi.snapshot.json` (`max_length` im Schema),
`scripts/dev/tests/test_e2e_api.py` (neu).

## Datenmodell / API / Migrationen
Keine Migration. Das API-Schema nimmt einen `name` über 255 Zeichen mit 422 ab (heute speichert es ihn); der OpenAPI-Snapshot
ändert sich um `maxLength`.

## Trade-offs
Das Limit 255 folgt `label`; die Anzeige fügt Servername und Suffix hinzu, das Feld bleibt der Eingabetext.

## Risiken & Rollback
Ein Client, der einen `name` über 255 Zeichen schickt, bekommt 422; die Desktop-UI kürzt nicht selbst, ein solcher
Name ist unrealistisch. Je Task ein Commit, einzeln rückgängig zu machen.

## Doku-Impact
Keine (internes Laden, Testfrist, Kommentar; das Feldlimit steht im OpenAPI-Schema).

## Offene Fragen
Punkt 5 (ConnectionEditor, eigene Roadmap-Zeile): Empfehlung, das Namensfeld bis zur geladenen Serverliste zu sperren.
