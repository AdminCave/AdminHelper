<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent übernimmt FRP-Tunnel selbst — Task-Ledger
Status: aktiv · Branch: feature/agent-frpc-sync · Review: pro Task
Spec: docs/features/agent-frpc-sync.md (Roadmap R-0398)
Heavy: linux-full + scenario --agents 1 --tunnel --enforce + windows — Server-API (`config-hash`) und Agent-Paket im Stack (`run.sh integration`, `upgrade_path`); vor dem Merge der Multibox-Lauf, weil nur er den Datenpfad über frps mit echtem mTLS zeigt: Tunnel nach dem Provisionieren, Reload bei offener SSH-Sitzung, `run --once` ohne Tunnel grün (Kevin hat den `--tunnel`-Lauf vor dem Merge erlaubt); `windows`, weil sich Agent-Plattformcode und der Provisionier-Pfad unter Windows ändern (No-ops, Sync-Config immer)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: `config-hash` → `{"hash": null}` nur ohne FRP-Config, bei 0 Tunneln bleibt der Hash der leeren TOML; Reload über die lokale frpc-Admin-API auch auf Agent-Hosts, als letzte Agent-Task; Agent-Timer bleibt 5 min (schnellerer Abgleich = eigene Zeile); Windows bleibt No-op; Bestandshosts ohne gespeicherten Key einmal neu provisionieren. Bis T6 startet der Agent frpc bei jeder Änderung neu wie heute. Vor dem Start: R-0384 (`feature/agent-identity-lock`, ändert `provision.go`/`provision_test.go`) gemergt.

### T1 — Server: `config-hash` ohne FRP-Config liefert `{"hash": null}`  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/provision_router.py, apps/server/tests/test_frp_provision_sync.py, apps/server/tests/test_provisioning.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/server.html, docs/en/developer/server.html, apps/server/tests/test_mtls_scope.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2f6dbc1c 2026-10-16T13:26:44+02:00
Review: approve (.ah-out/review/agent-frpc-sync/T1.verdict.json)
Änderung: `get_provision_config_hash` (`provision_router.py:83`) antwortet ohne FRP-Config mit 200 `{"hash": null}` statt der 404 aus `_load_sync_inputs` (`:57`); Scope-Prüfung (403) und 404 „Server nicht gefunden“ (`:53`) bleiben, ebenso `/config` (404 ohne Config) und der Hash bei 0 Tunneln. Neue Testdatei `tests/test_frp_provision_sync.py` (SPDX-Header `# SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `# SPDX-License-Identifier: GPL-3.0-or-later`), zuerst rot: ohne Config → 200 `null`; Config ohne Tunnel → Hash der leeren TOML (nicht null); unbekannter Server → 404; fremder Server → 403; Generator-Vertrag: `generate_frpc_toml` (`config_generator.py:156`) enthält weder `loginFailExit` noch `webServer`, und jede Zeile vor dem ersten `[[proxies]]` (`:184`) ist Common-Teil (keine Proxy-Schlüssel davor). `test_provisioning.py:283-284` erwartet heute 404 ohne FRP-Config → auf 200 mit `hash is None` umstellen (keine Test-Löschung). OpenAPI-Snapshot muss unverändert bleiben (Schema `{}`); ändert er sich, `[?]`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_provision_sync.py tests/test_provisioning.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (`:163`, `null` ohne FRP-Config) · docs/developer/server.html + docs/en/developer/server.html (`:99`, Abgleich auch ohne FRP-Config ohne Fehler)

### T2 — Agent: Sync-Config bei jeder Provisionierung  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cad7599c 2026-10-16T13:38:20+02:00
Review: approve (.ah-out/review/agent-frpc-sync/T2.verdict.json)
Änderung: Das Schreiben von `/etc/frp/adminhelper.conf` samt Verzeichnissen und CA-Kopie (`apply.go:52-95`, `WriteKeyValue` `:91`) wird als exportierte `frpc.WriteSyncConfig(SyncConfigParams)` herausgelöst; `Apply` ruft sie weiter. `provision.Run` ruft `WriteSyncConfig` nach der Aktivierung immer, auch ohne FRP-Paket (`provision.go:152`); der Paketkommentar (`:10`) stimmt danach. Die Meldung bei fehlender Sync-Config (`sync.go:26`) nennt den Ausweg („vor dieser Version ohne Tunnel provisioniert? Für Tunnel einmal neu provisionieren“), bleibt Info und Exit 0. Tests zuerst rot, Namen mit `SyncConfig`: `WriteSyncConfig` schreibt URL, Key, Server-ID, CA/INSECURE mit 0600; `provision.Run` gegen einen httptest-TLS-Server mit `frp: null` hinterlässt `adminhelper.conf` (Temp-Verzeichnisse über `ADMINHELPER_FRP_DIR`/`ADMINHELPER_MONITOR_DIR`, systemctl über Seams).
Verify: bash scripts/dev/verify.sh agent --strict -- -run SyncConfig
Doku: keine (intern; sichtbar wird es mit T4)
Abhängt von: T1

### T3 — Agent: „nichts zu tun“ ohne Fehler (Hash `null`, TOML ohne Proxies)  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/platform_linux.go, apps/agent/internal/frpc/platform_windows.go
Änderung: `Sync` liest `hash: null` → frpc stoppen und deaktivieren (neuer Seam `disableService`, Linux `systemctl disable --now frpc.service`, Windows No-op), `frpc.toml` und `.config-hash` löschen, nil. Neuer Hash mit TOML ohne `[[proxies]]`-Zeile → stoppen und deaktivieren, `frpc.toml` löschen (enthält das frps-Token), Hash speichern, nil. Seams wie `restartService` (`sync.go:20`) als Paketvariablen, im Test gestubbt. Tests zuerst rot in `sync_flow_test.go` (Namen mit `TestSync`): `null` → disable gerufen, Dateien weg, kein Fehler; leere TOML → disable, `frpc.toml` weg, Hash gespeichert; zweiter Lauf mit gleichem Hash → kein weiterer Aufruf.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestSync
Doku: keine (intern; sichtbar wird es mit T4)
Abhängt von: T2

### T4 — Agent: erster Tunnel startet frpc dauerhaft, `loginFailExit = false`  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/platform_linux.go, apps/agent/internal/frpc/platform_windows.go, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, CHANGELOG.md
Änderung: Neuer Hash mit Proxies: der Agent stellt dem Server-Text `loginFailExit = false` als erste Zeile voran (Top-Level, vor jeder Tabelle; frp v0.69.1 `pkg/config/v1/client.go` ~Z. 54–57/88 vorher per WebFetch gegenprüfen), schreibt atomar (0600, wie `sync.go:91-96`); frpc nicht aktiv (Seam `isActive`, Linux `systemctl is-active --quiet frpc.service`) → `enableFrpcService` (`platform_linux.go:15`, `enable --now`, überlebt Reboot); aktiv → Neustart wie heute (`sync.go:100`). Hash erst nach Erfolg (`:107`). Windows: Seams No-op. Tests zuerst rot (Namen mit `TestSync`): erste Config bei inaktivem frpc → enable statt restart; Datei beginnt mit `loginFailExit = false`, Rest byte-gleich zum Server-Text; Hash = Hash des Server-Texts; aktiver frpc → restart.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestSync
Doku: docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html (später angelegter Tunnel greift beim nächsten Agent-Lauf, ohne Tunnel kein frpc, Bestandshosts ohne Tunnel einmal neu provisionieren; Abschnitt um `:149` „Neu provisionieren“) · CHANGELOG.md (Fixed)
Abhängt von: T3

### T5 — Agent: Neu-Provisionieren übernimmt die neue Config sofort  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/apply.go, apps/agent/internal/frpc/apply_test.go, apps/agent/internal/frpc/sync.go, apps/agent/internal/provision/provision.go
Änderung: `Apply` schreibt `frpc.toml` nicht mehr selbst und ruft nicht nur `enableFrpcService` (`apply.go:102`, `:120`, `:125`), sondern nutzt denselben Anwende-Pfad wie `Sync` (aus T3/T4 als gemeinsame Funktion in `sync.go`): Vorspann, enable bzw. Neustart bei laufendem frpc, leere TOML → stoppen. Gespeichert wird der Hash des Server-Texts statt `writeConfigHash` über die lokal geschriebene Datei (`sync.go:131`; heute weicht er unter Windows durch `rewriteIdentityPaths` ab). `provision.Run` ohne FRP-Paket ruft nach `WriteSyncConfig` den Pfad „nichts zu tun“ (stoppt einen frpc aus einer früheren Provisionierung). Tests zuerst rot, Namen mit `Reprovision`: laufender frpc + neues Paket → Neustart und neue Datei; gespeicherter Hash = Hash des Paket-Texts; Provision ohne Paket bei vorhandenem frpc → disable, Dateien weg.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Reprovision
Doku: keine (intern; CHANGELOG-Eintrag aus T4 deckt es)
Abhängt von: T4

### T6 — Agent: Tunnel-Änderungen per Reload über die lokale frpc-Admin-API  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/admin.go, apps/agent/internal/frpc/admin_test.go, apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, docs/developer/agent.html, docs/en/developer/agent.html
Änderung: Neue `admin.go` + `admin_test.go` (SPDX-Header `// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`): `/etc/frp/admin.conf` (0600) mit Port und Passwort (32 Zufallsbytes, base64url); Port über `net.Listen("tcp", "127.0.0.1:0")`. Der Vorspann aus T4 bekommt `webServer.addr = "127.0.0.1"`, `webServer.port`, `webServer.user`, `webServer.password`. `Sync`: Common-Teil (Text vor dem ersten `[[proxies]]`) alt = neu und frpc aktiv → Reload (Seam, Linux `frpc reload -c /etc/frp/frpc.toml`), Fehler → Neustart; Common-Teil anders → Neustart. frpc soll laufen, ist aber nicht aktiv (Admin-Port nach Reboot belegt) → neuer Port, Datei neu, enable/Neustart. Reload-Semantik vorher per WebFetch gegen frp v0.69.1 prüfen (README „Hot-Reloading“, `client/service.go`). Windows: No-op. Tests zuerst rot, Namen mit `Reload`: `admin.conf` 0600 und stabil über Läufe; nur Proxies geändert → Reload, kein Restart; Token geändert → Restart; Reload-Fehler → Restart; inaktiv trotz Proxies → neuer Port.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Reload
Doku: docs/developer/agent.html + docs/en/developer/agent.html (Ablauf des Abgleichs, lokale Admin-API: nur 127.0.0.1, Passwort in 0600-Datei, Reload statt Neustart)
Abhängt von: T5

### T7 — Szenario: Tunnel nach dem Provisionieren, Reload bei offener Sitzung  [ ]
Komponente: scripts · Dateien: scripts/tests/box_tunnelbox.sh, scripts/tests/multibox.sh, scripts/tests/multibox_test.sh
Änderung: Der Multibox-`--tunnel`-Ablauf belegt Ziel 2 und 3 auf echten Boxen: (a) der Tunnel-Agent wird provisioniert, bevor sein Tunnel existiert; der Orchestrator legt den Tunnel danach über die API an (ohne `box_serverbox.sh` zu ändern, das frps-Vorhaben ändert dort den frps-Start), `adminhelper-agent run --once` → `frpc.service` aktiv und `enabled`, frps meldet die Registrierung; (b) der Visitor hält eine SSH-Sitzung über den Tunnel offen, der Orchestrator legt einen zweiten Tunnel an, `adminhelper-agent frpc sync` → Journal zeigt Reload, kein Neustart, die Sitzung lebt (neue Marker, z. B. `TUNNEL_LATE_OK`, `VIS_SESSION_SURVIVED`). `run --once` auf der Agent-Box ohne Tunnel bleibt `AGENT_RUN_OK` (bestehender Marker). `multibox_test.sh` (hermetisch) prüft die neuen Marker-Auswertungen. Hinweis: Änderungen unter `scripts/` machen den PR zu einem, den Kevin merged (CLAUDE.md §2).
Verify: bash scripts/dev/verify.sh scripts --strict -- multibox_test
Doku: keine (Test-Harness; `docs/developer/` nur, falls die Szenario-Beschreibung dort die Schritte aufzählt — vorher greppen)
Abhängt von: T6
