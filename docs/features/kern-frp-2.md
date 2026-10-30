<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-frp-2 — FRP-Generator: Namen aus Altzeilen, Config je Server, Warnungen

Zug der Kern-Session (Roadmap R-0972, R-0973, R-0969, R-0970, R-0971).

## Problem
- **R-0972:** Der Generator schreibt Server- und Nutzernamen (`user`, `allowUsers`, `serverUser`, Visitor-`user`) als
  TOML-Strings, prüft sie aber selbst nicht (`apps/server/app/modules/frp/config_generator.py` `generate_frpc_toml`,
  `generate_visitor_toml`). Die Schemas prüfen neue Werte (`servers/schemas._validate_server_name`,
  `users/schemas._USERNAME_PATTERN`); Zeilen von vor diesen Prüfungen bleiben, wie sie sind. Für Tunnel-Felder
  gibt es diese Prüfung im Generator schon (`without_refused_fields`), für Namen nicht. Details privat.
- **R-0973:** `GET /api/frp/generate/frpc-toml/{server_id}` nimmt die FRP-Config aus `tunnels[0].frp_config_id`
  (`apps/server/app/modules/frp/generate_router.py` `gen_frpc_toml`), der Agent-Sync und das Provisioning-Bundle
  dagegen aus `frp._helpers.frpc_sync_inputs` (älteste Config, nur ihre Tunnel). Hat ein Server Tunnel in zwei
  Configs, liefert die Route eine andere `frpc.toml` als die, die der Agent bekommt.
- **R-0969:** `without_refused_fields` und `without_unreachable_local` warnen bei jedem Aufruf; Sync und Hash-Poll
  rufen sie für jeden Host alle paar Sekunden. `without_refused_extra_config` warnt je Tunnel nur einmal
  (`_first_warning`).
- **R-0970:** Docstring und Doku sagen „die die API heute ablehnen würde“; geprüft werden aber nur die Zeichen
  (`_reject_toml_breakers`), nicht etwa die Mindestlänge eines Secrets. Ein Secret unter 16 Zeichen bleibt drin.
- **R-0971:** `without_secretless_stcp` loggt den Tunnelnamen mit `%s`, bevor `without_refused_fields` einen Namen
  mit Steuerzeichen aussortiert hat: eine Logzeile kann so mehrzeilig werden.

## Ziel & Nicht-Ziele
- Ziel: Ein Name, dessen Zeichen die API ablehnt (`_reject_toml_breakers`), landet in keiner generierten TOML.
  Ein solcher Servername als frpc-`user`: der Host bekommt den Text ohne aktiven Tunnel (kein Token, keine
  `[[proxies]]`) und ohne `user`-Zeile; die Route `frpc-toml` antwortet 404 wie ohne aktiven Tunnel, das Bulk-ZIP
  lässt den Server aus. Ein solcher Nutzername fällt aus `allowUsers` (Warnung); bleibt keiner, gilt der bestehende
  Fallback für eine leere Liste. Ein Visitor-Tunnel, dessen Zielservername abgelehnt wird, fällt aus der
  Visitor-TOML; ein abgelehnter Visitor-Nutzername ergibt 404 bzw. keinen Eintrag im Bulk-ZIP.
- Ziel: `frpc-toml` liefert genau den Text des Agent-Syncs (`frpc_sync_inputs`).
- Ziel: jede Auslass-Warnung des Generators einmal je Tunnel und Grund, Namen mit `%r`.
- Nicht-Ziel: Altzeilen migrieren; die Schemas ändern.

## Betroffene Komponenten & Dateien
- `server`: `app/modules/frp/config_generator.py`, `app/modules/frp/generate_router.py`,
  `tests/test_frp_toml_roundtrip.py`, `tests/test_frp_permissions.py`.
- Doku: `docs/developer/server.html`, `docs/en/developer/server.html` (Generator-Tabelle), `changelog.d/kern-frp-2.md`.

## Datenmodell / API / Migrationen
Keine Migration. `frpc-toml` antwortet für einen Server mit Tunneln außerhalb der Sync-Config künftig wie der Sync
(404, wenn dort kein aktiver Tunnel steht). Kein Vertrags-Drift zu Web, Desktop oder Agent: Form und Felder bleiben.

## Externe Integrationen
FRP-TOML (frpc `user`, `allowUsers`, Visitor `serverUser`): https://gofrp.org/en/docs/reference/client-configures/ —
nur die Werte ändern sich, nicht die Schlüssel.

## Trade-offs & Alternativen
- Abgelehnten Namen escapen statt auslassen: verworfen. Der Name ist zugleich FRP-Kennung (`user.proxy`), ein
  umgeschriebener Name passt nicht mehr zum Visitor. Auslassen wie bei `without_refused_fields`.
- Für einen abgelehnten frpc-`user` einen Fehler werfen: verworfen, Sync und Hash würden für den Host scheitern;
  der Text ohne Tunnel hält den Host im bekannten Zustand.

## Risiken & Rollback
Ein Host mit einem Altnamen verliert seine Tunnel, bis der Name über die API korrigiert ist (Warnung im Log). Rollback:
Revert der Task-Commits.

## Doku-Impact
`docs/developer/server.html` und `docs/en/developer/server.html`: Generator-Tabelle (Namen, Wortlaut der Prüfung,
Warnungen einmal) und Sync-Absatz zur Route `frpc-toml`. Changelog über `changelog.d/kern-frp-2.md`.

## Offene Fragen
Keine.
