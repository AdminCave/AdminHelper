<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Drift: Agent-Deployment, README/DEVELOPMENT, Desktop-Entwicklerdoku — Task-Ledger
Status: erledigt · Branch: feature/doc-drift · Review: am Ende
Spec: Roadmap R-0386, R-0388, R-0442, R-0444
Heavy: none — nur Doku
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vier BUG-Zeilen in einem Doku-Kurz-Ledger (Kevin 2026-10-17). Das Soll ist der Code: Jede Task nennt unter
`Semantik:` die Stellen, gegen die die Doku geprüft wird; der builder greppt sie und die Doku-Zeilen vor dem
Schreiben neu. Doku hat keinen roten Test: `Beweis:` ist ein grep, der auf `HEAD:` die veralteten Stellen zeigt
und nach der Task nichts mehr liefert; `Verify:` ist der formale Lauf (die echten `<code>`-Pfade unter `docs/`
prüft `doc-smoke.py` in der PR-CI, `.github/workflows/ci.yml:874`). Feste Zählwerte (Commands, Tests, Stores,
Komponenten) werden nicht nachgezählt, sondern fallen weg: Sie sind die Ursache dieser Drift (so schon R-0383).
Kein CHANGELOG-Eintrag: reine Doku-Korrektur ohne Verhaltensänderung (wie R-0383). „Beifang“ sind Stellen im
selben Block mit demselben Fehler, die keine Zeile nennt; jede Task führt sie getrennt auf.

T3 baut erst nach dem Merge von R-0429 (`feature/desktop-pre-workspaces`): R-0429 ändert dieselben Abschnitte von
`desktop.html` (Absatz nach dem Baum, Connect-Flow Schritt 4) und mit `connectFlow.ts` die Wahrheit des
Connect-Flows. T1 und T2 hängen nicht daran.

### T1 — R-0442: Agent-Deployment nennt das Tunnel-Zertifikat aus dem Enrollment  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f18dfbb1 2026-10-18T07:18:50+02:00
Review: am Ende (Branch-Review)
Änderung: EN `:148` („a client certificate signed by the FRP CA“) sagt stattdessen, dass frpc das Client-Zertifikat nutzt, das der Agent beim mTLS-Enrollment vom `ca-issuer` holt (Absatz darunter, `:149`, `/etc/adminhelper/identity/`); eine server-eigene FRP-CA gibt es nicht mehr. DE `:136` („weder einen Server-URL noch ein FRP-Client-Zertifikat“) nennt das Client-Zertifikat ohne „FRP-“. Beifang DE `:39` („lädt beim Erst-Start mit einem Provision-Token sein Client-Zertifikat und startet `frpc.service`“): beim Provisionieren, das Zertifikat aus dem Enrollment, `frpc.service` nur mit aktivem Tunnel (wie DE `:147`). Nichts Neues über das Enrollment hinaus, was EN `:149` und DE `:148` schon sagen.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html (die Task ist die Doku)
Beweis: main@5855a9b5 · `grep -n -o -E 'signed by the FRP CA|FRP-Client-Zertifikat|beim Erst-Start mit einem Provision-Token sein Client-Zertifikat' docs/en/admin/agent-deployment.html docs/admin/agent-deployment.html` → EN `:148`, DE `:39`, `:136`; nach der Task leer
Dedup-Key: bug:docs:agent-deployment:frp-ca-cert-wording
HEAD: 5855a9b5
Semantik: Soll ist der Code — `apps/server/app/modules/frp/config_generator.py:23-26` („The frp tunnel reuses that single tunnel-scoped identity rather than a separate server-minted client cert“), `_tls_agent_block` `:129-140` (`certFile = "{_AGENT_IDENTITY_DIR}/agent.crt"`), `apps/agent/internal/enroll/enroll.go:37-38`; dazu `docs/developer/server.html:142` — „Der Server signiert keine FRP-Zertifikate mehr (D6, F3).“

### T2 — R-0388, R-0444, R-0386 (Notiz): README und DEVELOPMENT auf dem Stand des Codes  [x]
Komponente: scripts · Dateien: README.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ce8af910 2026-10-18T07:26:45+02:00
Review: am Ende (Branch-Review)
Änderung: (1) R-0388: Die Router-Zeile im Monitoring-Block (README `:441`, DEVELOPMENT `:1398`) nennt auch `maintenance`. (2) R-0444: README `:106` sagt Seitenleiste statt Header; README `:109` ersetzt „Session is persisted — no re-login needed on restart“ durch: im Server-Modus bei jedem Start Anmeldung mit Passwort, Server-URL und Benutzername vorausgefüllt; „Local and Sync modes remain fully functional“ bleibt. (3) Notiz zu R-0386: „32 Tauri commands“ (README `:463`, DEVELOPMENT `:1421`; registriert sind heute 34) wird zahlenlos („all Tauri commands“ bzw. „alle Tauri-Commands“). Beifang im selben Baum: `checkers/` ohne `forecast` (README `:440`, DEVELOPMENT `:1397`), und die Zählwerte des Desktop-UI-Blocks (README `:476`, `:477`, `:480`; DEVELOPMENT `:1434`, `:1435`, `:1437`, `:1439`; heute u. a. 13 Stores, 54 Komponenten, 76 Testdateien, die neben dem Code liegen, nicht in `vitest.setup.ts`) werden zahlenlos. Server- und Web-Block bleiben unberührt.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: README.md, DEVELOPMENT.md (die Task ist die Doku; README gibt es nur englisch, DEVELOPMENT nur deutsch)
Beweis: main@5855a9b5 · `grep -n -E 'routers/ +# admin, agent, alerts, checks, templates$|32 Tauri|tunnel indicator in the header|Session is persisted' README.md DEVELOPMENT.md` → README `:106`, `:109`, `:441`, `:463`, DEVELOPMENT `:1398`, `:1421`; Beifang `grep -n -E 'checkers/ +# agent, smart, http, ping, tcp, plugins$|invoke\(\)|12 [Ss]tores|~46|~250' README.md DEVELOPMENT.md` → README `:440`, `:476`, `:477`, `:480`, DEVELOPMENT `:1397`, `:1434`, `:1435`, `:1437`, `:1439`; beide nach der Task leer
Dedup-Key: bug:docs:README.md:monitoring-routers bug:docs:readme:tunnel-indicator-and-session bug:docs:desktop.html:stale-tree-example
HEAD: 5855a9b5
Semantik: Soll ist der Code — `apps/monitoring/app/routers/__init__.py:14-21` (`all_routers` mit `maintenance_router`, `:19`), `apps/monitoring/app/checkers/__init__.py:41` (`disk_forecast`), `apps/desktop/ui/src/components/AppShell.svelte:211` (`<TunnelIndicator />` in `<aside class="sidebar">` `:177-254`, der Header ist `:256-279`), `apps/desktop/ui/src/lib/stores/session.ts:81` (`hydrate` setzt `session: null`), `apps/desktop/src-tauri/src/main.rs:91-126` (`generate_handler!`); dazu `docs/developer/desktop.html:143` — „Aus Sicherheitsgründen stellt der Client beim Start <em>keine</em> gespeicherte Session mehr wieder her“ und `docs/developer/monitoring.html:78` — „routers/ admin.py / agent.py / alerts.py / checks.py / templates.py / maintenance.py“

### T3 — R-0386: desktop.html beschreibt Baum, Connect-Flow und Tests wie der Code  [x]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @3a1e9f14 2026-10-19T07:13:08+02:00
Review: am Ende (Branch-Review)
Änderung: Erst nach dem Merge von R-0429, Zeilen dann neu greppen. (1) Der Baum (`:38-64`, DE+EN) nennt nur, was `git ls-files apps/desktop` zeigt: unter `src-tauri/src/` Dateien statt der Verzeichnisse `commands/`, `frp/`, `keyring/`, `http/`, `rdp/` (`commands.rs`, `frpc.rs`, `keyring_store.rs`, `http_client.rs` …; den Race-Guard trägt `ui/src/lib/stores/connectFlow.ts`), `connection/` als SSH/RDP/Web ohne VNC, `binaries/` unter `src-tauri/`, `tauri.conf.json` mit dem echten `beforeBuildCommand`, die Vitest-Zeile ohne Zahl. (2) Das Rust-Beispiel `connect_rdp` (`:97-109`) entfällt; ein Satz sagt, dass die Correlation-ID als `correlation_id` an `open_connection` bzw. `open_connection_stored` geht. (3) Der Connect-Flow (`:151-159`) folgt `connectFlow.ts`: Prüfung der Verbindung, bei RDP zuerst Keyring oder `PasswordPrompt`, dann `resolve_connection` mit den Mappings des Tunnel-Stores, bei RDP mit Correlation-ID `open_connection` bzw. `open_connection_stored`; kein `state = 'connecting'`, kein VNC, kein Abbau des Tunnels nach dem Ende der Verbindung (den frpc führt der Tunnel-Store). (4) `vitest (41 Tests)` (`:168`) ohne Zahl. (5) Die `models/`-Zeile im Baum (`:57`) nennt alle Dateien unter `ui/src/lib/models/` ohne Tests, also auch `ansible`, `maintenance`, `monitoring` und `shared` (Kevin 2026-10-18). (6) Keyring-Secrets (`:122`): Service ist `com.admincave.adminhelper` statt Prefix `adminhelper:`, der Account eines RDP-Passworts `rdp|<host>|<port>|<user>|<domain>` (kleingeschrieben) statt `<connection-id>` (Fund aus R-0429 T4). Die Command-Tabelle bleibt unverändert; `ipc.inventory.test.ts` liest sie auf beiden Seiten.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/bridge/ipc.inventory.test.ts
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (die Task ist die Doku)
Beweis: main@5855a9b5 · `grep -n -E '(commands|frp|keyring|http|rdp)/ |connect_rdp|41 (Tests|tests|Vitest)|RDP/SSH/VNC' docs/developer/desktop.html docs/en/developer/desktop.html` → je Seite `:42-47`, `:64`, `:101`, `:154`, `:157`, `:168`; `grep -n -F '&rarr; <code>../apps/desktop/ui' docs/developer/desktop.html docs/en/developer/desktop.html` → je Seite `:49`; `grep -rn connect_rdp apps/desktop` → leer; nach der Task liefern die ersten beiden nichts
Dedup-Key: bug:docs:desktop.html:stale-tree-example
HEAD: 5855a9b5
Semantik: Soll ist der Code — `apps/desktop/src-tauri/src/` (einziges Verzeichnis `connection/`), `apps/desktop/src-tauri/src/main.rs:91-126` (`generate_handler!`, kein `connect_rdp`), `apps/desktop/src-tauri/src/connection/mod.rs:24-35` (Ssh, Rdp, Web), `apps/desktop/src-tauri/tauri.conf.json:7`, `:9`, `:37`, `apps/desktop/ui/src/lib/stores/connectFlow.ts:136`, `:179`, `:202`, `:213`, `:222`, `:225-226`, `apps/desktop/src-tauri/src/commands.rs:216`, `:381`, `git ls-files apps/desktop/ui/src/lib/models`, `apps/desktop/src-tauri/src/password.rs:17-31` (`rdp_storage_key`), `apps/desktop/src-tauri/src/keyring_store.rs:25` (`SERVICE`); dazu `docs/developer/desktop.html:112` — „Der Desktop-Client vergibt deshalb pro Versuch eine <strong>Correlation-ID</strong> (<code>crypto.randomUUID()</code>)“
