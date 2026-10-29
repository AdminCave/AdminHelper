<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: frpc-Config nach einer Ablehnung und nach einem Update

## Problem / Motivation

Der Agent übernimmt den frpc-Text des Servers nur in der Form, die `generate_frpc_toml` schreibt
(`checkServerConfig`, `apps/agent/internal/frpc/servertoml.go`). Zwei Lücken im Abgleich (`Sync`,
`apps/agent/internal/frpc/sync.go:45`):

1. **Ablehnung:** Besteht ein Text die Prüfung nicht, endet `applyConfig` (`sync.go:231`) mit dem Fehler und lässt
   frpc unverändert. frpc läuft auf der alten `frpc.toml` weiter, und jede weitere Tunnel-Änderung des Hosts hängt,
   bis der Server wieder einen annehmbaren Text liefert. Was auf dem Host läuft, ist dann nicht das, was der Server
   will, und auch nicht das, was die Prüfung zuletzt angenommen hat.
2. **Agent-Update:** Bei gleichem Server-Hash holt der Agent den Text nicht neu (`sync.go:112`). Eine `frpc.toml`,
   die eine ältere Agent-Version geschrieben hat, läuft weiter, ohne dass die Prüfung der neuen Version sie je
   gesehen hat — bis sich auf dem Server etwas an den Tunneln des Hosts ändert.

## Ziel & Nicht-Ziele

Ziel:
- Ein abgelehnter Server-Text stoppt frpc (Sync und Provisionierung): frpc stoppen und deaktivieren, `frpc.toml`
  und Hash löschen, Warnung mit Zeile und Schlüssel (wie heute, ohne Wert). Der nächste Lauf holt und prüft erneut;
  nimmt er an, startet frpc wie bei einem neuen Tunnel. Kevin 2026-10-29.
- Nach einem Agent-Update holt der nächste Lauf den Text einmal, auch bei gleichem Hash, und prüft ihn. Besteht er,
  bleibt frpc unberührt (kein Reload, kein Neustart); besteht er nicht, gilt Ziel 1.

Nicht-Ziele:
- Keine Änderung an `checkServerConfig` selbst und an der Form des Server-Texts.
- Kein Aufheben einer zuletzt angenommenen Config als Rückfall (Kevin 2026-10-29: stoppen).
- Keine Server-Änderung; der Server lässt Tunnel mit abgelehnter `extra_config` schon weg
  (`without_refused_extra_config`, `apps/server/app/modules/frp/config_generator.py`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | agent | `apps/agent/internal/frpc/sync.go`, `apps/agent/internal/frpc/sync_flow_test.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `CHANGELOG.md` |
| T2 | agent | `apps/agent/internal/frpc/sync.go`, `apps/agent/internal/frpc/sync_flow_test.go`, `apps/agent/cmd/adminhelper-agent/main.go`, `docs/developer/agent.html`, `docs/en/developer/agent.html`, `CHANGELOG.md` |

## Datenmodell / API / Migrationen

Keine API-, Schema- oder Migrationsänderung. Neu im FRP-Verzeichnis des Agents: eine Datei mit der Agent-Version,
die den aktuellen Text zuletzt geprüft hat (T2). Fehlt sie (jeder Agent vor diesem Paket), zählt das als
„nicht geprüft“: der erste Lauf nach dem Update holt und prüft einmal.

## Externe Integrationen

Keine neue. frpc wird wie bisher über `stopFrpc`/`startFrpc` (systemd bzw. Windows-Dienst) gesteuert.

## Trade-offs & Alternativen

1. **Stoppen statt weiterlaufen lassen (Kevin 2026-10-29).** Fail-closed: alle Tunnel des Hosts sind aus, bis der
   Server einen annehmbaren Text liefert. Alternative „zuletzt angenommenen Text aufheben und prüfen“ verworfen:
   mehr Zustand im FRP-Verzeichnis für einen Fall, der nur bei Versions-Schiefstand auftritt.
2. **Marker = Agent-Version statt einer Prüf-Revision.** Eine von Hand gepflegte Revisionsnummer müsste bei jeder
   Verschärfung der Prüfung erhöht werden; das vergisst man. Die Version wechselt mit jedem Update von selbst. Preis:
   ein Update ohne Änderung an der Prüfung holt den Text einmal umsonst (ein HTTP-Abruf). Dev-Builds tragen
   `dev` und prüfen untereinander nicht neu.
3. **Bei bestandener Nachprüfung nichts anfassen.** Ein Reload bei gleichem Text brächte nichts und kostete im
   schlechtesten Fall einen Neustart; geschrieben wird nur der Marker.

## Risiken & Rollback

- Ein Host, dessen Server einen Text liefert, den der neue Agent ablehnt, verliert nach dem Update seine Tunnel. Das
  ist gewollt; der Log nennt Zeile und Schlüssel, die Abhilfe liegt am Server (Tunnel bzw. `extra_config`).
- Rollback: Revert der zwei Task-Commits; ein älterer Agent ignoriert die Marker-Datei.

## Doku-Impact

`docs/developer/agent.html` (Tabelle „Lage / Ablauf“ des Abgleichs, DE+EN): zwei Zeilen (Ablehnung, nach einem
Update). `docs/admin/agent-deployment.html` (Absatz „Tunnel nach der Provisionierung“, DE+EN): ein Satz zur Ablehnung.
CHANGELOG (Changed).

## Offene Fragen

Keine; die Verhaltensfrage hat Kevin am 2026-10-29 entschieden.
