# FRP: Anmeldung eines Hosts an seinen Schluessel binden — Task-Ledger
Status: erledigt · Branch: feature/kern-frp-10 · Review: pro Task
Spec: docs/features/kern-frp-10.md (Roadmap R-1363)
Heavy: scenario --tunnel — FRP-Tunnel-Datenpfad ueber Hosts (frpc-Anmeldung an frps); ask-first
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-12 (kern-frp-5 Gate): zwei Releases, Scharfschalten nach dem Release mit dem Agent-Teil (v0.47.0).
- Kevin 2026-11-25 (Notiz R-1363): faellig. Der Weckeintrag „ab 2027-02-25“ in der Roadmap stammt aus der Durchsicht
  davor.
- R-1317 faehrt nicht mit (Frage an Kevin, Zug kern-frp-11).

### T1 — Generator: Schluessel des Hosts auf Wurzelebene der frpc.toml  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_config_generator.py, apps/agent/internal/frpc/testdata/server_frpc.toml, apps/server/tests/test_frps_policy_live.py, apps/server/tests/test_frp_provision_sync.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3c9e21757 2026-11-26T12:29:30+01:00
Review: approve (.ah-out/review/kern-frp-10/T1.verdict.json)
Änderung: `generate_frpc_toml` schreibt `metadatas.ahProxyKey = "<Schluessel>"` nach dem TLS-Block und vor dem ersten `[[proxies]]`, wie `auth.token` nur mit aktiven Tunneln. Test: Zeile steht auf Wurzelebene mit dem Schluessel der Generation des Servers; ohne aktive Tunnel fehlt sie.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_proxy_key.py tests/test_frp_provision_sync.py
Doku: → T3

### T2 — Supervisor: Plugin auch fuer die Op Login  [x]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor_policy.py, apps/server/tests/test_frps_policy_live.py, apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d8ecd51f7 2026-11-26T12:49:39+01:00
Review: approve (.ah-out/review/kern-frp-10/T2.verdict.json)
Änderung: `plugin_block` registriert `ops = ["Login", "NewProxy"]`, Kopfkommentar nachziehen. Tests: Block mit beiden Ops; echtes frpc: Host mit Schluessel meldet sich an, Host ohne oder mit falschem Schluessel wird abgewiesen, Visitor-User ohne Schluessel meldet sich an. Mitpruefen: Work-Conn-Pool ueber fremde run_id und user+client_id-Registry (Befund privat).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor_policy.py tests/test_frps_policy_live.py
Doku: → T3
Abhängt von: T1

### T3 — Doku: Anmeldung des Hosts, Update-Reihenfolge, CHANGELOG  [x]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-frp-10.md, docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d57c10295 2026-11-26T12:54:20+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Abschnitt „Pruefung der Proxy-Anmeldungen“ DE+EN: frps prueft auch die Anmeldung eines Hosts, Logzeilen `login admitted`/`login refused`, Agents vor dem Server-Update auf mindestens v0.47.0, handverteilte frpc.toml neu verteilen. CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-frp-10.md
Task-Review: am Ende
