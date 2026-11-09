# Einheitliche Namen — Task-Ledger
Status: aktiv · Branch: feature/arch-namen · Review: pro Task
Spec: docs/features/arch-namen.md (Roadmap R-1210, R-1211)
Heavy: scenario --tunnel — FRP-Kennungen (frpc user, Proxy-, Visitor-Namen) wechseln auf IDs; der echte 3-Host-Datenpfad beweist es, ask-first. Die Desktop-Tunnel-Suiten und die Live-Specs aus T10 fährt der Sammellauf linux-full
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entscheidungen Kevin 2026-11-09 (Spec, Ziel 1–6): 1a Kennungen über IDs, 2a ein Pflichtfeld Name + Adresse folgt,
3a Zusatz statt eigener Name, 4a Kopien leeren, 5a Servername eindeutig ab jetzt.

### T1 — FRP-Kennungen über IDs, Statuszuordnung exakt (R-1210 1a, R-1211)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/app/modules/frp/status_router.py, apps/server/app/modules/frp/generate_router.py, apps/server/app/modules/frp/provision_router.py, apps/server/app/modules/provisioning/helpers.py, apps/server/tests/test_frp_status.py, apps/server/tests/test_frp_toml_roundtrip.py, apps/server/tests/test_frp_input_hardening.py, apps/server/app/modules/servers/schemas.py, apps/server/tests/test_config_generator.py, apps/server/tests/test_frp_permissions.py, apps/server/tests/test_frp_provision_sync.py, apps/agent/internal/frpc/testdata/server_frpc.toml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9e3ee785a 2026-11-09T13:49:03+01:00
Review: approve (.ah-out/review/arch-namen/T1.verdict.json)
Änderung: frpc `user` = Server-ID, Proxy-Name = Tunnel-ID, Visitor `name`/`serverName`/`serverUser` aus den IDs, Tunnel nach ID sortiert; Prüfungen, die nur wegen Namen im TOML bestanden, entfallen (Spec „FRP-Wire“), der ZIP-Pfad behält seine. Die Statusseite ordnet über den Schlüssel `{server_id}.{tunnel_id}` zu. Erst der rote Test: ein Proxy, dessen Server- und Tunnelname Punkte tragen, findet seinen Tunnel (heute nicht). Neun Dateien: Generator, seine vier Aufrufer und die Tests sind ein Wire-Wechsel.
Beweis: main@f8b5364f apps/server/app/modules/frp/status_router.py:107-111 (`name.split(".")[-1]`); Dedup-Key: BUG:server:frp/status_router.py:proxy_name_split
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_status.py tests/test_frp_toml_roundtrip.py tests/test_frp_input_hardening.py tests/test_frp_provision_sync.py tests/test_frp_permissions.py tests/test_frp_provision_authz.py tests/test_provisioning.py
Doku: → T12

### T2 — Server: ein Pflichtfeld Name, Adresse folgt, Name eindeutig (R-1210 2a, 5a)  [x]
Komponente: server · Dateien: apps/server/app/modules/servers/models.py, apps/server/app/modules/servers/schemas.py, apps/server/app/modules/servers/router.py, apps/server/alembic/versions/b1c3d5e7f9a1_server_hostname_follows_name.py, apps/server/tests/test_server_hostname_migration.py, apps/server/tests/test_servers_schemas.py, apps/server/tests/test_servers_summary.py, apps/server/tests/test_internal_servers.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_server_name_and_address.py, apps/server/app/modules/users/router.py, apps/desktop/ui/src/lib/api/types.ts
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9fe8ea00f 2026-11-09T14:08:37+01:00
Review: approve (.ah-out/review/arch-namen/T2.verdict.json)
Änderung: `servers.hostname` nullable, `NULL` = Adresse folgt dem Namen; Ausgabe `hostname` = wirksame Adresse, neu `customHostname`; Eingabe leer/gleich Name → `NULL`; jeder Leser von `Server.hostname` im Server liest die wirksame Adresse (grep). Anlegen/Umbenennen mit vergebenem Namen (ohne Groß-/Kleinschreibung) → 409. Desktop-Typ `Server` bekommt `customHostname` (Vertragstest gegen den Snapshot; Lauf `verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts` als Zusatzbeleg, ein `Verify:` nimmt Argumente nur für eine Komponente). Alembic-Revision mit Datenteil und Downgrade (Spec), Migrationstest. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_server_name_and_address.py tests/test_server_hostname_migration.py tests/test_servers_schemas.py tests/test_servers_summary.py tests/test_internal_servers.py tests/test_servers_name_windows.py tests/test_servers_authz.py tests/test_openapi_snapshot.py tests/test_alembic_builtin.py tests/test_migrations_smoke.py
Doku: → T12

### T3 — Verbindungen: Anzeigename aus dem Server, Zusatz statt Name (R-1210 3a, 4a)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/app/modules/frp/_helpers.py, apps/server/app/modules/servers/router.py, apps/server/alembic/versions/c2d4e6f8a0b2_connection_derived_names.py, apps/server/tests/test_connection_derived_names.py, apps/server/tests/test_connection_names_migration.py, apps/server/tests/test_connection_schemas.py, apps/server/tests/openapi.snapshot.json, apps/server/app/modules/servers/models.py, apps/desktop/ui/src/lib/api/types.ts, apps/server/tests/test_pagination.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @463ead602 2026-11-09T14:57:24+01:00
Review: approve (.ah-out/review/arch-namen/T3.verdict.json)
Änderung: Bei Verbindungen mit Server hält `name` den Zusatz; Ausgabe `name` = Anzeigename (`{server} · {Zusatz|SSH|RDP|Web}`, über Tunnel ` (FRP)`), neu `label`; Eingabe `label`, `name` alter Clients nach der Kopien-Regel; Auto-Verbindung ohne Namenskopie; Löschen eines Servers schreibt die Anzeigenamen fest; Audit-Label = Anzeigename; Server ohne N+1 laden. Migration 4a mit Downgrade und Test. Zehn Dateien: eine Vertragsänderung samt Migration. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connection_derived_names.py tests/test_connection_names_migration.py tests/test_connection_schemas.py tests/test_connections_import.py tests/test_connections_storage.py tests/test_connections_authz.py tests/test_connections_isolation.py tests/test_connections_options.py tests/test_connections_options_authz.py tests/test_connection_sessions.py tests/test_frp_tunnels.py tests/test_servers_authz.py tests/test_pagination.py tests/test_audit_wiring.py tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_alembic_builtin.py tests/test_migrations_smoke.py
Doku: → T12
Abhängt von: T2

### T4 — Tunnel: Anzeigename, Zusatz, keine Namens-Eindeutigkeit (R-1210 3a, 4a)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/models.py, apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/tunnel_router.py, apps/server/alembic/versions/d3e5f7a9b1c3_tunnel_derived_names.py, apps/server/tests/test_tunnel_names_migration.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/openapi.snapshot.json, apps/server/tests/test_tunnel_derived_names.py, apps/server/app/modules/frp/status_router.py, apps/desktop/ui/src/lib/api/types.ts, apps/server/tests/test_frp_tunnel_access.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @de7aa503f 2026-11-09T15:31:57+01:00
Review: approve (.ah-out/review/arch-namen/T4.verdict.json)
Änderung: `frp_tunnels.name` = Zusatz (`''` = keiner), Unique-Constraint und 409 entfallen; Ausgabe `name` = Anzeigename wie die Auto-Verbindung, neu `label`; Eingabe `label` (optional), `name` alter Clients nach der Kopien-Regel; Liste nach Server und Protokoll sortiert. Migration 4a (Kopien leeren) mit Downgrade (ID-Suffix, Constraint zurück) und Test. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_tunnel_derived_names.py tests/test_tunnel_names_migration.py tests/test_frp_tunnels.py tests/test_frp_tunnel_access.py tests/test_frp_status.py tests/test_frp_input_hardening.py tests/test_frp_permissions.py tests/test_frp_config.py tests/test_connection_derived_names.py tests/test_servers_authz.py tests/test_response_shapes.py tests/test_openapi_snapshot.py tests/test_alembic_builtin.py tests/test_migrations_smoke.py
Doku: → T12
Abhängt von: T1, T3

### T5 — Desktop: Server-Dialog mit einem Pflichtfeld (R-1210 2a, 5a)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/ServerModal.svelte, apps/desktop/ui/src/components/infra/ServerModal.test.ts, apps/desktop/ui/src/lib/models/infra.ts, apps/desktop/ui/src/lib/models/infra.test.ts, apps/desktop/ui/src/lib/stores/infra.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/infra.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @fda60e291 2026-11-09T15:35:02+01:00
Review: approve (.ah-out/review/arch-namen/T5.verdict.json)
Änderung: Pflicht ist nur „Name (FQDN)“; „Adresse (falls abweichend)“ optional, Platzhalter = Name, gefüllt nur bei `customHostname`; ein 409 meldet „Name schon vergeben“ in der Statusleiste wie die übrigen Prüfungen des Dialogs; Typen um `customHostname` ergänzt (Vertragstest).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/ServerModal.test.ts src/lib/models/infra.test.ts src/lib/stores/infra.test.ts src/lib/api/types.contract.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T2

### T6 — Desktop: Verbindungsdialoge mit Zusatz, Gruppierung nach Server (R-1210 3a)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/ServerConnectionModal.svelte, apps/desktop/ui/src/components/infra/ServerConnectionModal.test.ts, apps/desktop/ui/src/lib/models/serverConnection.ts, apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/lib/models/connection.ts, apps/desktop/ui/src/lib/models/connectionList.ts, apps/desktop/ui/src/lib/models/connectionList.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/infra/tabs/ConnectionsTab.svelte, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/components/infra/modals.regression.test.ts, apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts, apps/desktop/ui/src/lib/models/connection.test.ts, apps/desktop/ui/src/lib/models/serverConnection.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e2e385f9b 2026-11-09T16:13:45+01:00
Review: approve (.ah-out/review/arch-namen/T6.verdict.json)
Änderung: Mit Server: Feld „Zusatz (optional)“ statt Name, Vorschau des Anzeigenamens, Host aus der Serveradresse vorbelegt; ohne Server Name Pflicht wie heute; Formulare lesen `label`. Gruppierung „Server“ nach `serverId` (Servername), ohne Server nach Host. Stellen, die selbst Namen bilden (`Dashboard.svelte` `conn.name || target(conn)`), prüfen. Neun Dateien: ein Formularvertrag in zwei Dialogen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/ServerConnectionModal.test.ts src/components/infra/modals.regression.test.ts src/lib/models/serverConnection.test.ts src/lib/models/connection.test.ts src/lib/models/connectionList.test.ts src/components/ConnectionEditor.tabs.test.ts src/lib/api/types.contract.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T3

### T7 — Desktop: Tunnel-Dialog ohne Namensfeld (R-1210 3a)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/TunnelModal.svelte, apps/desktop/ui/src/components/infra/TunnelModal.test.ts, apps/desktop/ui/src/lib/models/frpTunnel.ts, apps/desktop/ui/src/lib/models/frpTunnel.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/infra/tabs/TunnelsTab.svelte, apps/desktop/ui/src/components/infra/modals.regression.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0ab74ba5c 2026-11-09T16:18:44+01:00
Review: approve (.ah-out/review/arch-namen/T7.verdict.json)
Änderung: Statt des Pflichtfelds Name (Platzhalter `k01-lnx1-ssh`) ein optionaler Zusatz mit Vorschau des Anzeigenamens; Formular liest `label`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/TunnelModal.test.ts src/components/infra/modals.regression.test.ts src/lib/models/frpTunnel.test.ts src/lib/api/types.contract.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T4

### T8 — Desktop-RS: Tunnelname eines Visitors aus der Tunnelliste, Titel mit Mittelpunkt (R-1210 1a, 3a)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/port_registry.rs, apps/desktop/src-tauri/src/validation.rs, docs/features/arch-namen.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @9eeee24ca 2026-11-09T15:49:28+01:00
Review: approve (.ah-out/review/arch-namen/T8.verdict.json)
Änderung: Eine Verbindung ohne verknüpften Tunnel, die auf einen Visitor-Port zeigt, nennt den Tunnel mit diesem Visitor-Port aus der Tunnelliste (Anzeigename), sonst wie bisher den Visitor-Namen (künftig `<uuid>-visitor`). `sanitize_window_title` lässt den Mittelpunkt `·` der Anzeigenamen durch (Fenster- und xfreerdp-Titel). Die Portkarte gibt einem vom Server umbenannten Visitor (gleicher Server-Port) seinen bisherigen lokalen Port, sonst fände ssh dort einen fremden Host-Key; mit Test.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (Anzeige im Desktop, kein dokumentiertes Verhalten)
Abhängt von: T1

### T9 — Web: FRP-Status zeigt den Tunnel, nicht den Proxy-Namen (R-1210 1a)  [x]
Komponente: web · Dateien: apps/web/src/modals/FrpStatusModal.svelte, apps/web/src/modals/FrpStatusModal.test.ts, apps/web/src/lib/api/types.ts, apps/web/src/lib/api/types.contract.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @113eae3c1 2026-11-09T16:27:11+01:00
Review: approve (.ah-out/review/arch-namen/T9.verdict.json)
Änderung: Spalte Name zeigt `p.tunnel?.name` (Anzeigename), ohne Tunnel den Proxy-Namen; Test für beide Fälle. Neue Testdatei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh web --strict -- FrpStatusModal types.contract
Doku: → T12
Abhängt von: T1

### T10 — Desktop-E2E: Live-Specs auf Name/Zusatz umstellen (R-1210)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/server-crud.live.js, apps/desktop/e2e/test/specs/tunnel-create.live.js, apps/desktop/e2e/test/specs/tunnel-crud.live.js, apps/desktop/e2e/test/specs/connection-crud.live.js
Änderung: Server nur mit Name anlegen, Adresse folgt; Tunnel ohne Namensfeld, Zusatz ändern, Zeile zeigt `<server> · …`; Verbindung am Server mit Zusatz, Zeile zeigt den Anzeigenamen. Live-Lauf im Sammellauf linux-full.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Tests)
Abhängt von: T5, T6, T7

### T11 — Test-Skripte: frpc/frps-Logs über die Tunnel-ID suchen (R-1210 1a)  [ ]
Komponente: scripts · Dateien: scripts/tests/multibox.sh, scripts/tests/box_tunnelbox.sh, scripts/tests/box_serverbox.sh, scripts/tests/multibox_test.sh
Änderung: `frps_registered`/`proxy_started` und der MISSING-Abgleich der Serverbox suchen `[<server_id>.<tunnel_id>]` bzw. `[<tunnel_id>]`; die Skripte lesen die IDs der angelegten Tunnel aus der API statt der Namen.
Verify: bash scripts/dev/verify.sh scripts --strict -- multibox_test
Doku: keine (Test-Skripte)
Abhängt von: T1

### T12 — Doku DE+EN und CHANGELOG (R-1210, R-1211)  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/developer/server.html, docs/en/developer/server.html, changelog.d/arch-namen.md
Änderung: Kennungen über IDs und einmaliger Tunnel-Neustart nach dem Update (frp-tunnel), Generator/Visitor/Statuszuordnung, Anzeigename, `label`, `customHostname`, Eindeutigkeit (server.html); weitere Seiten mit Namensfeldern per grep (`Hostname`, `Proxy-Name`, `via FRP`) nachziehen und in `Dateien:` aufnehmen; CHANGELOG-Fragment (Changed, Fixed R-1211). Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/frp-tunnel.html DE+EN · docs/developer/server.html DE+EN · changelog.d/arch-namen.md
Abhängt von: T1, T2, T3, T4

### T13 — Desktop-RS: RDP-Pins über die Tunnel-ID statt den Anzeigenamen (R-1210)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/tunnel.rs, apps/desktop/src-tauri/src/rdp_embedded/tofu.rs, apps/desktop/src-tauri/src/port_registry.rs, apps/desktop/src-tauri/src/rdp_embedded/mod.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @b42210b66 2026-11-09T16:16:09+01:00
Review: approve (.ah-out/review/arch-namen/T13.verdict.json)
Änderung: Die Identität eines RDP-Zertifikat-Pins über einen Tunnel nennt den Tunnel bei seiner ID (stabil bei jeder Umbenennung, eindeutig), nicht beim Namen, der seit T4 der abgeleitete Anzeigename ist; `ResolvedConnection` trägt dazu die Tunnel-ID (verknüpfter Pfad: die ID der Zuordnung; Literal-Pfad: die der Zuordnung am Server-Port, sonst die aus `<id>-visitor`). Der Name bleibt nur Anzeige. Bestehende Pins werden einmal neu bestätigt (mit dem Update ändern sich die Namen ohnehin). Dazu der Nit aus T8: der Test mit belegtem altem Port bindet beide Ports gleichzeitig. Quelle: security T8 (privat, tasks/private/sec-arch-namen-notes.md).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T12
Abhängt von: T8
