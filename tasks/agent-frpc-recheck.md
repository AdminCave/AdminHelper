<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: frpc-Config nach einer Ablehnung und nach einem Update — Task-Ledger
Status: erledigt · Branch: feature/agent-frpc-recheck · Review: am Ende
Spec: docs/features/agent-frpc-recheck.md
Heavy: linux-full — `apps/agent` (Abgleich und Provisionierung von frpc); Windows über den CI-Job `agent-windows` (`go test ./...` nativ, `sync.go` ist plattformgemeinsam), keine Windows-VM. Kein `scenario`: ein angenommener Server-Text nimmt denselben Weg wie heute, der FRP-Datenpfad ändert sich nicht
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Ein abgelehnter Server-Text stoppt frpc  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, docs/developer/agent.html, docs/en/developer/agent.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md, apps/agent/internal/frpc/servertoml_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @776c87aa 2026-10-29T04:43:16+01:00
Review: am Ende (Branch-Review)
Änderung: In `applyConfig` (`sync.go:216`) endet eine Ablehnung durch `checkServerConfig` (`:231`) nicht mehr ohne Folgen: frpc stoppen und deaktivieren (`stopFrpc`, `:374`, löscht `frpc.toml`), den Hash löschen, Warnung mit dem Fehler der Prüfung (Zeile und Schlüssel, nie ein Wert), dann den Fehler zurückgeben. Gilt für Sync und Provisionierung (`Apply`, `apply.go:109`), beide gehen über `applyConfig`. Der nächste Lauf findet keinen Hash, holt und prüft erneut; ein dann angenommener Text startet frpc wie ein neuer Tunnel. Tests in `sync_flow_test.go` mit den vorhandenen Fakes (`TestSyncStopsFrpcOnAConfigWithoutATunnel`, `:772`, als Muster): (a) frpc läuft auf einer `frpc.toml`, der Server liefert einen Text mit `plugin.type` in einem Proxy → Sync endet mit Fehler, frpc deaktiviert, `frpc.toml` und Hash weg; (b) der nächste Sync mit einem annehmbaren Text startet frpc und schreibt den Hash; (c) Provisionierung mit abgelehntem Text → dasselbe wie (a); (d) Gegenstück: ein angenommener Text ändert am bisherigen Ablauf nichts (Reload wie heute). Zuerst rot: (a), (c).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/...
Doku: docs/developer/agent.html + docs/en/developer/agent.html (Tabelle „Lage / Ablauf“: neue Zeile „Server-Text besteht die Prüfung nicht“ → frpc stoppen und deaktivieren, `frpc.toml` und Hash löschen, Warnung; der nächste Lauf prüft erneut) · docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html (Absatz „Tunnel nach der Provisionierung“: ein Satz — lehnt der Agent die Konfiguration des Servers ab, stoppt er frpc, bis der Server eine annehmbare liefert; der Grund steht im Agent-Log) · CHANGELOG.md (Changed, umlautfrei)

### T2 — Nach einem Agent-Update prüft der nächste Lauf die Config einmal neu  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/cmd/adminhelper-agent/main.go, docs/developer/agent.html, docs/en/developer/agent.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a674699f 2026-10-29T04:48:17+01:00
Review: am Ende (Branch-Review)
Änderung: Neue Datei im FRP-Verzeichnis (`checkedBy`, neben `.config-hash`, `0644`) mit der Agent-Version, die den gespeicherten Text zuletzt geprüft hat; die Version setzt `main` (`main.go`, wie `diagnostics.Run(version)`, `:77`) über eine Paket-Variable/Setter in `frpc`. `Sync`: bei gleichem Hash (`sync.go:112`) und Marker ≠ eigene Version (fehlender Marker eingeschlossen) Text holen, gegen den Hash prüfen, `checkServerConfig`; besteht er, nur den Marker schreiben (frpc unberührt, kein Reload); besteht er nicht, wie T1. `applyConfig` schreibt den Marker nach dem Hash (beide Zweige), `syncWithoutFrpConfig` (`:350`) löscht ihn mit. Tests in `sync_flow_test.go`: (a) gleicher Hash, kein Marker, annehmbarer Text → genau ein Abruf, Marker = Version, kein Reload und kein Neustart; (b) gleicher Hash, Marker alte Version, abgelehnter Text → wie T1 (a); (c) gleicher Hash, Marker = Version → kein Abruf (wie heute); (d) ein Wechsel ohne Tunnel löscht den Marker. Zuerst rot: (a), (b).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/... ./cmd/...
Doku: docs/developer/agent.html + docs/en/developer/agent.html (Absatz über der Tabelle: nach einem Agent-Update holt der erste Lauf den Text einmal und prüft ihn, auch bei gleichem Hash; besteht er, bleibt frpc unberührt; neue Datei im FRP-Verzeichnis nennen) · CHANGELOG.md (Changed, umlautfrei)
Abhängt von: T1

### T3 — Funde der Abschlussprüfung: Ablehnung bleibt ein Fehler, Marker am Hash  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/servertoml_test.go, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @20ebfb9c 2026-10-29T04:57:17+01:00
Review: am Ende (Branch-Review)
Änderung: (1) `refuseServerConfig` hängt einen gescheiterten Stopp ohne `%w` an die Ablehnung, damit `warnOnServiceFailure` (`apply.go:152`) sie nicht in eine Warnung verwandelt: eine abgelehnte Provisionierung endet immer mit Fehler (reviewer und security, branch). (2) Der Marker trägt Version und Hash (`<version> <hash>`) und gilt nur zum gespeicherten Hash. (3) Ohne gespeicherten Hash und für einen Text ohne `[[proxies]]` gibt es keine Nachprüfung (`applyConfig` prüft einen solchen nie). Tests: Ablehnung mit gescheitertem `disableService` bei Provisionierung und Sync → Fehler; Marker einer anderen Version oder eines anderen Hashs → Nachprüfung; kein Hash → kein Abruf. Gegenprobe: (1) mit `%w` rot.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/... ./cmd/...
Doku: docs/developer/agent.html + docs/en/developer/agent.html (Absatz zur Prüfung des Server-Texts: statt „schreibt dann nichts und startet nichts“ der Verweis auf die Tabellenzeile; Marker-Satz: Version und Hash)
Abhängt von: T2

### T4 — Doku: Satzfehler im Absatz zur Prüfung  [x]
Komponente: agent · Dateien: docs/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @44909249 2026-10-29T05:00:16+01:00
Review: am Ende (Branch-Review)
Änderung: „nie den Wert; er was dann folgt“ → „nie den Wert; was dann folgt“ (aus T3, security branch Runde 2). Die EN-Fassung ist richtig.
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/frpc/...
Doku: docs/developer/agent.html (nur DE)

## Entscheidungen
- 2026-10-29 Kevin: ein abgelehnter Server-Text stoppt frpc (fail-closed), statt auf der alten Datei weiterzulaufen; nach einem Agent-Update wird einmal neu geprüft.
