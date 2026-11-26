# FRP: Anmeldung eines Hosts an seinen Schluessel binden — Task-Ledger
Status: aktiv · Branch: feature/kern-frp-10 · Review: pro Task
Spec: docs/features/kern-frp-10.md (Roadmap R-1363)
Heavy: scenario --tunnel — FRP-Tunnel-Datenpfad ueber Hosts (frpc-Anmeldung an frps); ask-first
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-12 (kern-frp-5 Gate): zwei Releases, Scharfschalten nach dem Release mit dem Agent-Teil (v0.47.0).
- Kevin 2026-11-25 (Notiz R-1363): faellig. Der Weckeintrag „ab 2027-02-25“ in der Roadmap stammt aus der Durchsicht
  davor.
- R-1317 faehrt nicht mit (Frage an Kevin, Zug kern-frp-11).

### T1 — Generator: Schluessel des Hosts auf Wurzelebene der frpc.toml  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_config_generator.py
Änderung: `generate_frpc_toml` schreibt `metadatas.ahProxyKey = "<Schluessel>"` nach dem TLS-Block und vor dem ersten `[[proxies]]`, auch ohne aktive Tunnel. Test: Zeile steht auf Wurzelebene, mit und ohne Tunnel, mit der Generation des Servers.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_proxy_key.py
Doku: → T3

### T2 — Supervisor: Plugin auch fuer die Op Login  [ ]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor_policy.py, apps/server/tests/test_frps_policy_live.py
Änderung: `plugin_block` registriert `ops = ["Login", "NewProxy"]`, Kopfkommentar nachziehen. Tests: Block mit beiden Ops; echtes frpc: Host mit Schluessel meldet sich an, Host ohne oder mit falschem Schluessel wird abgewiesen, Visitor-User ohne Schluessel meldet sich an. Mitpruefen: Work-Conn-Pool ueber fremde run_id und user+client_id-Registry (Befund privat).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor_policy.py tests/test_frps_policy_live.py
Doku: → T3
Abhängt von: T1

### T3 — Doku: Anmeldung des Hosts, Update-Reihenfolge, CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-frp-10.md
Änderung: Abschnitt „Pruefung der Proxy-Anmeldungen“ DE+EN: frps prueft auch die Anmeldung eines Hosts, Logzeilen `login admitted`/`login refused`, Agents vor dem Server-Update auf mindestens v0.47.0, handverteilte frpc.toml neu verteilen. CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-frp-10.md
Task-Review: am Ende
