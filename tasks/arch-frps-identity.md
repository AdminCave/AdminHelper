# frps prüft Proxy-Anmeldungen — Task-Ledger
Status: geplant · Branch: feature/arch-frps-identity · Review: pro Task
Spec: docs/features/arch-frps-identity.md (Roadmap R-1215)
Heavy: scenario --tunnel — der echte Datenpfad Agent-frpc → frps mit Plugin → Desktop-Visitor beweist, dass ein Agent nach dem Sync seinen Schlüssel mitbringt und frps ihn zulässt; ask-first (Spec, Frage 3). Agent-Modul und Compose-Overlay fährt der Sammellauf linux-full
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen

- Session 2026-11-11 (Spec, Trade-offs): Variante A — Server-Plugin `NewProxy`, Schlüssel je Host abgeleitet aus
  `SECRET_KEY` in den Proxy-Metadaten, Policy-Datei vom Server; keine Migration, keine API-Änderung.
- Session 2026-11-11: Das Plugin liegt im Go-Modul des Agents (`cmd/frps-policy`, `internal/frpspolicy`), nur
  Standardbibliothek; es ändert den Inhalt einer Anmeldung nie und prüft genau die Felder, die der Generator schreibt.
- Session 2026-11-11: Plugin-Port fest auf Loopback, der Supervisor weicht bei Belegung durch `bindPort`,
  `vhostHTTPSPort` oder `webServer.port` aus (keine neue API-Ablehnung).
- Offen für Kevin: Spec, Fragen 1–3 (keine Task hängt daran; ein Übergangsfenster käme als eigene Task dazu).

### T1 — Server: Host-Schlüssel je Proxy im frpc.toml  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/proxy_key.py, apps/server/app/modules/frp/config_generator.py, apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_proxy_key.py, apps/server/tests/test_config_generator.py, apps/agent/internal/frpc/testdata/server_frpc.toml
Änderung: `proxy_key.py` (neu, SPDX-Header) leitet den Schlüssel je Server-ID ab (Spec, „Datenmodell“; `hmac.compare_digest`-taugliche Hex-Form) und liefert seinen SHA-256 für die Policy. `generate_frpc_toml` schreibt in jede `[[proxies]]`-Tabelle `metadatas.ahProxyKey`; der Schlüssel kommt in `_GENERATOR_PROXY_KEYS`, sodass `extra_config` ihn nicht setzen kann und gespeicherte Zeilen, die ihn tragen, aus der Konfiguration fallen. Tests: Ableitung deterministisch, je Server verschieden, hängt an `SECRET_KEY`; jede Proxy-Tabelle trägt ihn, ohne aktive Tunnel keiner; `extra_config` mit dem Schlüssel → 422. Die Agent-Fixture `server_frpc.toml` ist wieder die Generator-Ausgabe (`test_agent_fixture_is_the_generator_output`); Zusatzbeleg `verify.sh agent --strict` (die Go-Tests lesen dieselbe Fixture und belegen, dass heutige Agents den Schlüssel durchreichen).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_proxy_key.py tests/test_config_generator.py tests/test_frp_toml_roundtrip.py tests/test_frp_input_hardening.py tests/test_frp_provision_sync.py tests/test_frp_permissions.py tests/test_frp_tunnels.py
Doku: → T7

### T2 — Agent-Modul: frps-Plugin für NewProxy  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpspolicy/policy.go, apps/agent/internal/frpspolicy/handler.go, apps/agent/internal/frpspolicy/policy_test.go, apps/agent/internal/frpspolicy/handler_test.go, apps/agent/internal/frpspolicy/testdata/policy.json, apps/agent/internal/frpspolicy/testdata/newproxy.json, apps/agent/cmd/frps-policy/main.go
Änderung: Paket `frpspolicy` (SPDX-Header in jeder `.go`): Policy laden (Format `version` 1 aus der Spec; nur reguläre Datei, kein Symlink, Größengrenze, neu lesen bei geänderter Größe/mtime/Datei), Entscheidung über `NewProxy` (`user` bekannt, SHA-256 des Schlüssels aus `metas` gleich, konstantzeitig; `proxy_name == user + "." + tunnel_id` eines Tunnels dieses Servers; Typ, `custom_domains` (Reihenfolge exakt), `subdomain`, `group`, SHA-256 von `group_key` gleich der Policy), sonst Ablehnung mit allgemeinem Grund. HTTP-Handler nur `POST` mit `op=NewProxy`, Body-Grenze, Antwort `{reject, reject_reason, unchange: true}`, `GET /healthz`; Server mit Read-/Write-/Idle-Timeouts. Das Log nennt Server-ID, Proxy-Name und Entscheidung, nie Inhalt (Schlüssel, `sk`, Passwörter). `cmd/frps-policy`: Flags für Adresse, Pfad und Policy-Datei, Ende bei SIGTERM. Tests tabellarisch: Zulassen des eigenen Proxys je Typ; Ablehnen bei unbekanntem `user`, fehlendem oder falschem Schlüssel, Proxy-Name eines anderen Servers oder ohne Präfix, anderem Typ, abweichenden Domains/`subdomain`/Gruppe, fehlender, kaputter, zu großer oder verlinkter Policy, anderer Op, falscher Methode, zu großem Body, langsamem Client. Läuft auf Linux und Windows (CI-Job `agent-windows`); die Fixture `testdata/policy.json` liest auch der Server-Test in T3.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T7

### T3 — Server: Policy-Datei für frps schreiben  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/policy.py, apps/server/app/modules/frp/docker_manager.py, apps/server/app/modules/frp/tunnel_router.py, apps/server/app/modules/frp/config_router.py, apps/server/app/modules/servers/router.py, apps/server/app/main.py, apps/server/tests/test_frp_policy.py
Änderung: `policy.py` (neu, SPDX-Header) baut die Policy aus `active_tunnels` je Server (dieselbe Auswahl wie `generate_frpc_toml`, Felder wie der Generator sie schreibt) und schreibt sie deterministisch, 0644, atomar über den Schreibweg von `write_frps_config` (gleiches Temp-Präfix, damit `remove_stale_temp_files` Reste findet) nach `FRP_CONFIG_DIR/frps-policy.json`, nur bei geändertem Inhalt. Aufrufe nach dem Commit von Tunnel anlegen/ändern/löschen (`tunnel_router.py`), FRP-Konfiguration ändern/löschen (`config_router.py`), Server löschen (`servers/router.py`), beim Start (`_run_startup_tasks`) und alle 60 s im `lifespan`; ein Fehler beim Schreiben wird geloggt und bricht keinen Request. Tests: Ausgabe für eine Fixture-DB gleich `apps/agent/internal/frpspolicy/testdata/policy.json`; ausgelassene Tunnel (ohne Secret, verweigerte `extra_config`, ungültiger Port) fehlen; jeder Hook schreibt; Rechte 0644; kein Klartext-Schlüssel in der Datei; der periodische Abgleich stellt eine gelöschte oder veränderte Datei wieder her.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_policy.py tests/test_frp_tunnels.py tests/test_frp_config.py tests/test_frp_docker_manager.py tests/test_servers_authz.py tests/test_frp_provision_sync.py
Doku: → T7
Abhängt von: T1, T2

### T4 — frps-Image: mehrstufiger Build mit dem Plugin  [ ]
Komponente: server · Dateien: apps/frps/Dockerfile, apps/frps/Dockerfile.dockerignore, docker-compose.test.yml, .github/workflows/ci.yml, .github/workflows/docker.yml, apps/server/tests/test_frps_policy_image.py, apps/server/tests/test_compose_frps.py, apps/server/tests/test_release_images.py, apps/server/tests/test_frps_supervisor.py
Änderung: Go-Stufe auf einem per Digest gepinnten `golang`-Image ≥ der Toolchain aus `apps/agent/go.mod` baut `./cmd/frps-policy` statisch (`CGO_ENABLED=0`, `GOTOOLCHAIN=local`, `GOPROXY=off`, `-trimpath`); die frps-Stufe bleibt auf der gepinnten snowdreamtech-Basis, bekommt das Binary root-eigen mit 0711 und einen eigenen Nutzer `frps-policy` (UID/GID 10004, nicht in der Gruppe `frps`). Build-Kontext wird die Repo-Wurzel, `Dockerfile.dockerignore` (SPDX-Kommentar) lässt nur Supervisor und die Go-Quellen des Plugins zu. Mitgezogen: Compose-Overlay, CI-Matrix `docker-build`, `docker.yml`, der CI-Schritt, der die Basen der Image-Tests zieht (jede `FROM`-Basis, keine Stufen-Alias), und die Tests, die Kontext und Basis lesen (`_image()`/`_built_frps_image` in `test_frps_supervisor.py`; vorher `origin/main` mit #461 hineinmergen, das dieselbe Datei ändert). Neue Tests: Image baut, Binary vorhanden mit 0711 und root-eigen, Nutzer 10004 ohne Gruppe `frps`, kein setuid/setgid. Neun Dateien: jeder Ort, der das frps-Image baut, wechselt den Kontext gemeinsam. Der PR ändert damit `.github/workflows/`: Kevin merged.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_policy_image.py tests/test_compose_frps.py tests/test_release_images.py tests/test_frps_supervisor.py
Doku: → T7
Abhängt von: T2

### T5 — frps-Supervisor: Plugin starten, überwachen, anbinden  [ ]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor_policy.py
Änderung: Der Supervisor startet das Plugin als `frps-policy` vor frps auf `127.0.0.1` (fester Standard-Port, Ausweichen bei Belegung durch `bindPort`, `vhostHTTPSPort`, `webServer.port` der geprüften Konfiguration), wartet auf `/healthz`, hängt an seine geprüfte Kopie von frps.toml einen festen Block `[[httpPlugins]]` (`ops = ["NewProxy"]`) und lehnt `[[httpPlugins]]` im Eingang weiter ab. Jeder Poll prüft das Plugin (als `frps-fetch`, kurzes `--max-time`); bleibt es aus, beendet er es hart und startet es neu, das Log nennt den Neustart; beim Ende des Supervisors endet auch das Plugin. `kill_left` trifft das Plugin nicht (eigene UID). Tests in neuer Datei (die Helfer aus `test_frps_supervisor.py` mitbenutzt): Block in `current/frps.toml`, Port-Ausweichen, Eingang mit Plugin-Block abgelehnt, Neustart nach Ausfall, sauberes Ende; shellcheck wie in der CI.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor_policy.py tests/test_frps_supervisor.py
Doku: → T7
Abhängt von: T4

### T6 — Live: frps mit Plugin gegen echten frpc  [ ]
Komponente: server · Dateien: apps/server/tests/test_frps_policy_live.py, .github/workflows/ci.yml
Änderung: Neuer Docker-Test (SPDX-Header) mit dem gebauten frps-Image und `snowdreamtech/frpc` in der Version aus `FRP_VERSION`: Policy und frpc.toml aus dem echten Generator (T1, T3). Ein eigener `stcp`- und `https`-Proxy meldet sich an; abgelehnt werden: ohne oder mit falschem Schlüssel, ein Proxy-Name eines anderen Servers unter eigenem `user`, ein fremder `user` mit eigenem Schlüssel, eine nicht zugeordnete Domain, ein `tcp`-Proxy mit `remotePort`, eine gesetzte Gruppe; ohne Policy-Datei meldet sich nichts an. Der CI-Schritt der Image-Tests zieht zusätzlich das frpc-Image. Unter `--strict` ist ein Skip bei vorhandenem Docker rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_policy_live.py
Doku: → T7
Abhängt von: T3, T5

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/arch-frps-identity.md
Änderung: frp-tunnel: frps lässt nur die Proxies zu, die der Server für den Host erzeugt; nach dem Update kommen Tunnel mit dem nächsten Agent-Sync zurück (bis 5 min), manuell verteilte frpc.toml neu verteilen, ein `SECRET_KEY`-Wechsel verteilt neue Schlüssel über den Sync. betrieb/operations: zweiter Prozess im frps-Container, Neustart durch den Supervisor, Log-Zeilen. server.html: Policy-Datei, Schlüssel, Schreibzeitpunkte. Weitere Seiten zum Build des frps-Images per grep (`apps/frps`, `cicd.html`) nachziehen und in `Dateien:` aufnehmen. CHANGELOG-Fragment neutral (Changed; ohne SPDX-Kopf wie die übrigen Fragmente).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/frp-tunnel.html DE+EN · docs/admin/betrieb.html + docs/en/admin/operations.html · docs/developer/server.html DE+EN · changelog.d/arch-frps-identity.md
Task-Review: am Ende
Abhängt von: T1, T2, T3, T4, T5
