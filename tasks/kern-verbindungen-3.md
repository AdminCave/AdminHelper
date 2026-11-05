<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-3 — Task-Ledger
Status: aktiv · Branch: feature/kern-verbindungen-3 · Review: pro Task
Spec: docs/features/kern-verbindungen-3.md (Roadmap R-1066, R-1068)
Heavy: linux-full — Server-API (zwei Alembic-Revisionen, neue Endpunkte) und die Desktop-Journey Verbindungen; der Sammellauf fährt Stack und GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Rest aus kern-verbindungen-2 (T1–T3, T5–T8 dort verschoben), Kevins Antworten vom 2026-11-05 in der Spec. Stand `origin/main@a3645c00`.

### T1 — Server: Feld `options` an der Verbindung (R-1066)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/tests/test_connections_options.py, apps/server/tests/test_openapi_snapshot.py, apps/server/alembic/versions/a7c3e9d1f5b2_add_connection_options.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fcf37486 2026-11-05T09:05:57+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T1.verdict.json)
Änderung: Pydantic `ConnectionOptions` (`ssh`: jumpHost, forwards[{type L/R/D, listen, target}], agentForwarding, compression, keepalive, authMethod; `rdp`: scalingMode, windowMode, customSize, performanceProfile, drives, audio, printers, gateway, nla), alle optional, `extra="forbid"`, Formate an der Grenze geprüft (Host, Port 1–65535, kein führendes `-`, keine Steuerzeichen). Spalte `options` per Alembic-Revision (Downgrade entfernt sie), in Create/Update/Out, Import und Export. Neue Testdatei mit SPDX, Tests mit bösen Werten; OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_options.py tests/test_openapi_snapshot.py tests/test_migrations_smoke.py
Doku: → T8

### T2 — Desktop: SSH-Optionen in Modell, Validierung und Startargumenten (R-1066)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/session.rs, apps/desktop/src-tauri/src/tunnel.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @2ab8a7ed 2026-11-05T09:25:10+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T2.verdict.json)
Änderung: `Connection.options` (`#[serde(default)]`), Validierung wie T1, `build_ssh_args` setzt `-J`, `-L/-R/-D`, `-A`, `-C`, `-o ServerAliveInterval`, Auth-Art über `-o PreferredAuthentications`/`IdentitiesOnly`. Schalter vorher in `ssh(1)` nachlesen, Zitat unter `## Entscheidungen`. Tests mit bösen Werten.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ssh -- validation
Doku: → T8
Abhängt von: T1

### T3 — Desktop: RDP-Optionen je Verbindung, Linux-Argumente und .rdp-Datei (R-1066)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/connection/mod.rs
Änderung: Die RDP-Optionen der Verbindung überschreiben `RdpOptions` aus den Settings Feld für Feld; dazu `/drive`, `/sound`, `/printer`, `/gateway`, `/sec:nla` (FreeRDP) und die passenden Zeilen in `write_rdp_file` (Windows). Schalter vorher im FreeRDP-Wiki und in Microsofts „Supported RDP properties“ nachlesen, Zitate unter `## Entscheidungen`. Tests je Plattformzweig.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp
Doku: → T8
Abhängt von: T2

### T4 — Editor v2: Optionen und Anzeige (R-1066)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.options.test.ts, apps/desktop/ui/src/lib/models/connection.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Reiter Optionen (SSH: Jump-Host, Weiterleitungen hinzufügen/entfernen, Agent-Forwarding, Kompression, Keepalive; Auth-Art im Reiter Anmeldung) und Anzeige (RDP: Skalierung, Fenstermodus, Größe, Leistung mit „Global“ als Standard; Laufwerke, Audio, Drucker, Gateway, NLA). Leere Werte werden nicht gespeichert. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.options.test.ts src/components/ConnectionEditor.tabs.test.ts
Doku: → T8
Abhängt von: T2

### T5 — Server: Sitzungsverlauf, Tabelle und Endpunkte (R-1068)  [ ]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/tests/test_connection_sessions.py, apps/server/tests/test_openapi_snapshot.py
Änderung: Tabelle `connection_sessions` per Alembic-Revision (FK `ON DELETE CASCADE`, Downgrade entfernt sie); `touch` legt einen Eintrag an (Gerät: Name der Geräteregistrierung, sonst der vom Client gemeldete Hostname) und liefert `sessionId`; `POST /connections/{id}/sessions/{sid}/end`, `GET /connections/{id}/sessions?limit=` (Standard 5); Scope wie die Liste; Einträge älter als 90 Tage löscht der Server beim Schreiben. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connection_sessions.py tests/test_openapi_snapshot.py tests/test_migrations_smoke.py
Doku: → T8

### T6 — Desktop: Sitzungen schreiben, Ende bei RDP, lokaler Verlauf (R-1068)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts
Änderung: Verbinden legt eine Sitzung an (Server-Modus über `touch` mit Hostname, lokal in `sessions.json` je Workspace, höchstens 50 je Verbindung und 90 Tage), das Ende meldet der RDP-Exit-Monitor; neuer Befehl `list_sessions(connectionId)`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session
Doku: → T8
Abhängt von: T5

### T7 — Inspector: „Letzte Sitzungen“ (R-1068)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Der Inspector lädt die letzten 5 Sitzungen der gewählten Verbindung (Beginn, Dauer oder „—“, Gerät), leerer Zustand „Noch keine Sitzungen“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/ConnectionInspector.test.ts
Doku: → T8
Abhängt von: T6

### T8 — Doku DE+EN und Changelog (R-1066, R-1068)  [ ]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-verbindungen-3.md
Änderung: Admin-Doku: Optionen je Verbindung, Verlauf; Hinweis, dass ein alter Client beim Bearbeiten die Optionen verwirft. API-Referenz: `options`, Sitzungs-Endpunkte, Speicherdauer 90 Tage. Entwickler-Doku: Überschreibung der globalen RDP-Werte, lokaler Verlauf (50 je Verbindung). Changelog-Fragment (umlautfrei). `docs/admin/index.html` ändert auch feature/kern-pg-1 (eine Zeile, andere Stelle): vor dieser Task origin/main hineinmergen, falls pg-1 gemergt ist.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts
Doku: diese Task

## Entscheidungen
- T1: Form der Optionen. SSH: `jumpHost` als `[user@]host[:port]`, bis zu acht Hops mit Komma (wie `-J`); `forwards` höchstens 32 Einträge `{type L|R|D, listen "[bind:]port" (bind auch `*`), target "host:port"}`: L/R brauchen ein Ziel, D (SOCKS) nimmt keins; `keepalive` in Sekunden 1–3600 (`ServerAliveInterval`); `authMethod` key|agent|password. RDP: `scalingMode`, `windowMode`, `performanceProfile` mit den Werten der Desktop-Enums, `customSize` im Bereich von `parse_custom_size` (640x480–7680x4320); `drives`, `printers`, `nla` als bool, `audio` local|remote|off, `gateway` `host[:port]`. Host: Name aus `[A-Za-z0-9._-]` ohne führendes `-`, oder IPv6 in Klammern; Port 1–65535 als Regex, damit `0` und `65536` scheitern. Damit sind Leerzeichen, Steuerzeichen und Shell-Zeichen ausgeschlossen.
- T1: Gespeichert wird nur, was gesetzt ist (`_compact` entfernt None rekursiv, leer → NULL), damit „Feld fehlt“ der globale Standard bleibt. `PUT` ersetzt `options` als Ganzes (kein Merge), `null` löscht; ohne `options` im Body bleiben sie. Die Antwort trägt `options` nur, wenn gesetzt, wie `serverId`. `ConnectionOut.options` ist ein `dict`, nicht das Modell: eine Zeile soll die Liste nicht in einen 500 kippen, falls das Schema später strenger wird (wie `tags: Any`). Ein Extra-Eintrag `options` aus `extra_data` (vor der Spalte) wird nie ausgegeben, weil `options` jetzt ein bekanntes Feld ist.
- T2: Schalter nach ssh(1) und ssh_config(5) (OpenSSH 10.0p2): `-J destination` („Connect to the target host by first making an ssh connection to the jump host described by destination“; ProxyJump: „[user@]host[:port] … Multiple proxies may be separated by comma characters“), `-L/-R [bind_address:]port:host:hostport` („an empty address or `*' indicates that the port should be available from all interfaces“), `-D [bind_address:]port`. Booleans über `-o`, damit ein ausdrückliches Aus eine `~/.ssh/config` schlägt: ForwardAgent („Specifies whether the connection to the authentication agent (if any) will be forwarded to the remote machine … no (the default)“), Compression („yes or no (the default)“), ServerAliveInterval (Sekunden). Auth-Art: key → `PreferredAuthentications=publickey` + `IdentitiesOnly=yes` („only use the configured authentication identity and certificate files … even if ssh-agent(1) … offers more identities“), agent → `publickey`, password → `password,keyboard-interactive`. Alles vor `--`.
- T2: `validation.rs` prüft dieselben Formate wie das Server-Schema (Regex wie dort, Längen 1000/300, höchstens 32 Weiterleitungen, Keepalive 1–3600) und vertraut dem Server nicht: lokale Dateien und die Sync-URL gehen nicht durch ihn. Eine Sync-Verbindung mit ungültigen Optionen fällt wie bisher bei ungültigem Host aus der Liste (`sanitize_synced_connections`). Weiterleitungs-Typ und Auth-Art sind geschlossene Enums: Unbekanntes parst nicht. `Connection.options` ist `Option` mit `skip_serializing_if`, alte Dateien laden unverändert. Die TS-Typen stehen in `bridge/types.ts` (Rust-Spiegel) und `api/types.ts` (Server) getrennt, wie die Dateiköpfe es verlangen. Der `Verify:` nimmt zwei libtest-Filter (`-- ssh -- validation`), `cargo test` nimmt nur einen TESTNAME.
- T2: Die übrigen `Connection { … }`-Literale (nur Tests) bekommen `options: None` (Dateiliste per set-files).
