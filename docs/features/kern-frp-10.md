<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Anmeldung eines Hosts an seinen Schlüssel binden (kern-frp-10)

Roadmap: R-1363 · Ledger: `tasks/kern-frp-10.md`

## Problem / Motivation

Das Plugin `frps-policy` prüft heute jede Proxy-Anmeldung (Op `NewProxy`) gegen den Schlüssel des Hosts
(`metadatas.ahProxyKey` je Proxy). Die Anmeldung des frpc selbst (Op `Login`) prüft frps noch nicht gegen diesen
Schlüssel. Die Prüfung im Plugin (`DecideLogin`, `BoundRunID` in `apps/agent/internal/frpspolicy/policy.go`) und die
Annahme des Schlüssels auf Wurzelebene der `frpc.toml` durch den Agent (`serverRootKeys` in
`apps/agent/internal/frpc/servertoml.go`) kamen mit kern-frp-5 und stecken seit v0.47.0 im Release. Kevin hat am
Gate von kern-frp-5 (2026-11-12) zwei Releases festgelegt: erst der Agent-Teil, dann das Scharfschalten.

## Ziel & Nicht-Ziele

Ziel:
- Der Server schreibt den Schlüssel des Hosts zusätzlich auf Wurzelebene in die `frpc.toml`
  (`metadatas.ahProxyKey` vor dem ersten `[[proxies]]`), wie `auth.token` nur, wenn der Host aktive Tunnel hat
  (ohne sie meldet sich frpc nicht an).
- Der frps-Supervisor registriert das Plugin für die Ops `Login` und `NewProxy`.
- Ein Host meldet sich nur mit seinem Schlüssel an; Anmeldungen anderer Nutzer (STCP-Visitor des Desktops) bleiben
  wie heute zugelassen.

Nicht-Ziele:
- Kein Wechsel an der Prüflogik des Plugins (sie besteht seit kern-frp-5).
- Kein Übergangsfenster: ein Host mit Agent vor v0.47.0 wird nach dem Server-Update abgewiesen, bis sein Agent
  aktualisiert ist (Kevins Entscheidung „zwei Releases“).
- R-1317 fährt nicht mit (offene Frage an Kevin, Zug kern-frp-11).

## Betroffene Komponenten & Dateien

- Server: `apps/server/app/modules/frp/config_generator.py` (`generate_frpc_toml`), Tests
  `apps/server/tests/test_config_generator.py`.
- frps-Image: `apps/frps/frps-supervisor.sh` (`plugin_block`, Kopfkommentar), Tests
  `apps/server/tests/test_frps_supervisor_policy.py`, `apps/server/tests/test_frps_policy_live.py` (echtes frpc gegen
  das frps-Image).
- Doku: `docs/admin/betrieb.html`, `docs/en/admin/operations.html` (Abschnitt `frps-policy`), `changelog.d/kern-frp-10.md`.

## Datenmodell / API / Migrationen

Keine Migration, keine API-Änderung. Die `frpc.toml` bekommt eine Zeile mehr; der Agent nimmt sie seit v0.47.0 an.

## Externe Integrationen

frp v0.72.0, Server-Plugin-Ops (https://github.com/fatedier/frp/blob/v0.72.0/doc/server_plugin.md): `Login` trägt
`user`, `metas` (Wurzel-`metadatas` der `frpc.toml`) und `run_id`; das Plugin darf den Inhalt ändern.

## Trade-offs & Alternativen

- Schlüssel immer schreiben: ohne aktive Tunnel fehlt das Token, frpc meldet sich nicht an; der leere Text bliebe
  nicht leer. Empfehlung: wie das Token nur mit aktiven Tunneln.
- Login nur prüfen, wenn alle Agents ≥ v0.47.0 sind: verschiebt die Bindung ohne Ende. Verworfen (Kevin 2026-11-12).

## Risiken & Rollback

- Hosts mit altem Agent verlieren ihre Tunnel bis zum Agent-Update; Doku und CHANGELOG sagen: Agents zuerst
  aktualisieren. Handverteilte `frpc.toml` neu verteilen.
- Eine alte Arbeitskopie des Supervisors (Block nur mit `NewProxy`) besteht `check_copy` nicht mehr; der Supervisor
  verwirft sie beim Start und übernimmt die Eingabe neu (bestehendes Verhalten).
- Rollback: Release zurück; die Zeile in der `frpc.toml` schadet ohne Login-Prüfung nicht.

## Doku-Impact

Betriebsdoku DE+EN, Abschnitt „Prüfung der Proxy-Anmeldungen“: auch die Anmeldung eines Hosts wird geprüft, Logzeilen
`login admitted`/`login refused`, Update-Reihenfolge. CHANGELOG-Fragment.

## Offene Fragen

- Heavy `scenario --tunnel` vor dem Merge (ask-first, Kevin).
