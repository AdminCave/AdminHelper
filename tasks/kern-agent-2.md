<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-agent-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-agent-2 · Review: pro Task
Spec: docs/features/kern-agent-2.md (Roadmap R-0963, R-0964, R-0983, R-0965, R-0385)
Heavy: linux-full — `apps/agent` (Sammellauf: `agent_monitoring`, `upgrade_path`, Tunnel-E2E); `windows` ist der CI-Job `agent-windows`, weil `main.go` die Terminal-Eingabe auch unter Windows liest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Tasks

### T1 — FRP-Sync: Tunnel-Abbau ohne Antwort von systemd (R-0963)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_test.go, changelog.d/kern-agent-2.md, apps/agent/internal/frpc/sync_flow_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @1ed36cb3 2026-10-30T13:46:28+01:00
Review: approve (.ah-out/review/kern-agent-2/T1.verdict.json)
Änderung: Scheitert `disableService` in `stopFrpc` und lauscht der eigene frpc auf seinem Admin-Port, schreibt der Agent eine frpc.toml ohne Proxies und lädt sie über die Admin-API; der Fehler bleibt (kein Hash, nächster Lauf wiederholt systemd). Vorher frp-Verhalten bei null Proxies im Quelltext/der Doku belegen und mit echtem frpc proben, Ergebnis unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestSync|TestStopFrpc|TestServerConfig|TestHashConfig
Doku: changelog.d/kern-agent-2.md (neutral)

### T2 — Prüfung der Server-Konfig: Grenzen, kurze Meldungen, Reihenfolge (R-0964)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/servertoml.go, apps/agent/internal/frpc/servertoml_test.go, changelog.d/kern-agent-2.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @79b8450c 2026-10-30T13:57:31+01:00
Review: approve (.ah-out/review/kern-agent-2/T2.verdict.json)
Änderung: Grenze für Schlüssel je Tabelle und je Text (deutlich über dem, was der Generator für viele Tunnel schreibt); Schlüssel in Meldungen gekürzt; Segmentprüfung vor der Wertprüfung. Tests: Grenzen, gekürzte Meldung, Messung von Zeit/Heap des großen Falls vorher/nachher unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestServerConfig
Doku: changelog.d/kern-agent-2.md (neutral)

### T3 — provision --token-stdin: auf einem Terminal ohne Echo (R-0983)  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/provision_cmd_test.go, apps/agent/go.mod, apps/agent/go.sum, THIRD_PARTY_LICENSES.md, changelog.d/kern-agent-2.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @a3ed75e2 2026-10-30T14:00:27+01:00
Review: approve (.ah-out/review/kern-agent-2/T3.verdict.json)
Änderung: Ist stdin ein Terminal, liest `readStdinToken` mit `golang.org/x/term` ohne Echo (Prompt auf stderr); Pipe/Datei wie bisher, Grenze `maxStdinToken` bleibt. Test für den Nicht-Terminal-Weg und die Weiche (Terminal-Lesen selbst ist Plattform-I/O).
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestProvisionCmd|TestReadStdinToken
Doku: changelog.d/kern-agent-2.md (neutral)

### T4 — monitor init --api-key-stdin, Hinweise auf die stdin-Formen (R-0965)  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/main.go, apps/agent/cmd/adminhelper-agent/monitor_init_test.go, apps/agent/internal/enroll/client.go, apps/agent/deb/DEBIAN/postinst, README.md, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, changelog.d/kern-agent-2.md, apps/agent/rpm/adminhelper-agent.spec
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @0adbc262 2026-10-30T14:08:59+01:00
Review: approve (.ah-out/review/kern-agent-2/T4.verdict.json)
Änderung: `monitor init --api-key-stdin` mit demselben Leser wie T3 (genau eine von `--api-key`/`--api-key-stdin`); postinst, README, `reprovisionHint` und die CLI-Tabelle DE+EN zeigen die stdin-Formen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestMonitorInit|TestDocs|TestPackaging|TestProvisionCmd|TestReprovision
Doku: README.md · docs/admin/agent-deployment.html · docs/en/admin/agent-deployment.html · changelog.d/kern-agent-2.md
Abhängt von: T3

### T5 — Identität: Temp-Reste unter der Sperre räumen (R-0385)  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/enroll/renew.go, apps/agent/internal/enroll/enroll_test.go, apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, changelog.d/kern-agent-2.md
Änderung: Eine Funktion räumt `<agent.key|agent.crt|ca>.<n>.tmp` (exakter Name: Basis aus den drei Dateinamen, nur Ziffern, Suffix `.tmp`, reguläre Datei) im Identitätsverzeichnis; aufgerufen nur unter `LockIdentity` (Provisionierung nach dem Sperren, Erneuerung nach dem Sperren), nie aus `CheckStorable`. Tests: Reste weg, fremde Dateien und Nicht-Ziffern-Namen bleiben.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestStore|TestRenew|TestCheckStorable|TestStale|TestProvision
Doku: changelog.d/kern-agent-2.md

## Entscheidungen
- T1: frp stoppt bei einem Reload jeden Proxy, den die neue Konfig nicht mehr nennt (`UpdateAll` in `client/proxy/proxy_manager.go`, v0.69.1); Probe mit frpc 0.69.1 gegen frps: `frpc reload` ohne `[[proxies]]` meldet „reload success“, Log „proxy removed: [p1]“, der Remote-Port ist danach zu, frpc läuft weiter; `frpc verify -c` nimmt eine Konfig ohne Proxies an. Daher Abbau per Reload mit dem gemeinsamen Teil statt Prozess-Kill. Kein neues admin.conf im Fehlerpfad (`adminAPIListens` liest nur), damit ein fremder Port nie einen Reload bekommt; lauscht frpc nicht, hängt der Grund am Fehler.
- T2: Grenzen 4096 Schlüsselpfade je Tabelle, 131072 im Text (Schlüssel plus die Tabellen, die ein gepunkteter Schlüssel öffnet); ein Generator-Tunnel hat rund 20, 2000 Tunnel mit je 15 Schlüsseln liegen bei rund 40 000. Messung `checkServerConfig` (go test -overlay, Scratch, nicht eingecheckt): 2000 Tunnel (719 KB) 65 ms / 4 MiB, angenommen. Zeilen werden einzeln mit `strings.Cut` gelesen statt über `strings.Split`. Schlüssel und Tabellennamen in Meldungen auf 64 Bytes gekürzt (ASCII nach `serverKey`/`serverHead`).
