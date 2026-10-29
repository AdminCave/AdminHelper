<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Config-Erzeugung lässt Altzeilen aus, die die API heute ablehnt

Zug `kern-frp-1` (Roadmap R-0894, R-0926). Stand des Codes: `origin/main@33295e76`. Pfade ohne Präfix liegen unter
`apps/server/app/modules/frp/`.

## Problem / Motivation

1. **Tunnel-Felder aus Altzeilen (R-0894).** Die API prüft `name`, `local_ip`, `custom_domains` und `secret_key`
   eines Tunnels (`_reject_toml_breakers`, `schemas.py:27`, registriert ab `schemas.py:334`). Zeilen aus der Zeit vor
   dieser Prüfung erzeugt der Generator unverändert in die `frpc.toml` des Agents (`config_generator.py:394-406`) und
   in die Visitor-TOML (`config_generator.py:462-467`). Für `extra_config`, `local_port` und `visitor_port` gibt es
   solche Filter schon (`without_refused_extra_config`, `without_unreachable_local`, `without_unbindable_visitor`).
   Einzelheiten privat.
2. **Vorfilter der Routen (R-0926, REF).** `gen_frpc_toml` (`generate_router.py:77`) und der Bulk-ZIP
   (`generate_router.py:193-199`) filtern vor der 404-Prüfung mit `without_secretless_stcp` und
   `without_refused_extra_config`, aber nicht mit `without_unreachable_local`. Ein Server, dessen Tunnel alle ein
   ungültiges `local_port` haben, bekommt deshalb eine `frpc.toml` ohne Proxy (200) statt 404; die Kommentare
   `generate_router.py:81-83` und `:190-192` beschreiben die Menge nicht mehr.

## Ziel & Nicht-Ziele

Ziel: Der Generator lässt einen Tunnel aus, dessen gespeicherte Felder die API heute ablehnen würde, und warnt im
Log mit dem Tunnel-Namen (per `repr`), nie mit Werten. Die Routen nehmen dieselbe Menge wie `active_tunnels` und
antworten 404, wenn nichts bleibt. Nicht-Ziele: eine Migration, die Altzeilen umschreibt; Server-Namen
(`target_server.name`); Änderungen an Agent oder Desktop.

## Betroffene Komponenten & Dateien

`server`: `config_generator.py`, `generate_router.py`, Tests `apps/server/tests/test_config_generator.py` und
`apps/server/tests/test_frp_input_hardening.py`; Doku `docs/developer/server.html` + EN.

## Datenmodell / API / Migrationen

Keine Migration, kein neues Feld. Sichtbar: ein betroffener Tunnel fehlt in den erzeugten Configs (wie heute bei
`extra_config`); `GET /api/frp/generate/frpc-toml/{server_id}` antwortet 404 für einen Server ohne verbleibenden
Tunnel, wie heute schon bei Tunneln ohne Secret.

## Externe Integrationen

Keine neue. Das Format der erzeugten TOML bleibt.

## Trade-offs & Alternativen

- R-0894: Auslassen mit Warnung, wie bei den bestehenden Filtern. Alternative: Werte beim Erzeugen escapen —
  verworfen, ein alter Agent liest die Datei, und die API lässt solche Werte für neue Zeilen ohnehin nicht zu.
  Alternative Migration — verworfen, sie müsste Werte raten.
- R-0926: die Routen über dieselbe Filterkette wie `active_tunnels`, damit 404 und Inhalt nicht auseinanderlaufen.

## Risiken & Rollback

Ein Tunnel mit Altwert verschwindet aus der Config, bis ein Admin ihn über die API korrigiert; die Warnung nennt
ihn. Jede Task ein Commit, einzeln zurücknehmbar. T1 berührt die FRP-Config: `security` je Task.

## Doku-Impact

`docs/developer/server.html` (Tabelle der Generatoren, Zeilen zu `generate_frpc_toml` und `generate_visitor_toml`)
+ EN; `docs/developer/api-reference.html` (404- und Auslass-Bedingungen der Generate-Routen) + EN;
`changelog.d/kern-frp-1.md`.

## Offene Fragen

Keine.
