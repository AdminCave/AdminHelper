<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-3 — Task-Ledger
Status: bereit · Branch: feature/kern-verbindungen-3 · Review: pro Task
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

### T3 — Desktop: RDP-Optionen je Verbindung, Linux-Argumente und .rdp-Datei (R-1066)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/api/types.ts
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @371fb5fd 2026-11-05T09:43:22+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T3.verdict.json)
Änderung: Die RDP-Optionen der Verbindung überschreiben `RdpOptions` aus den Settings Feld für Feld; dazu `/drive`, `/sound`, `/printer`, `/gateway`, `/sec:nla` (FreeRDP) und die passenden Zeilen in `write_rdp_file` (Windows). Schalter vorher im FreeRDP-Wiki und in Microsofts „Supported RDP properties“ nachlesen, Zitate unter `## Entscheidungen`. Tests je Plattformzweig.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp
Doku: → T8
Abhängt von: T2

### T4 — Editor v2: Optionen und Anzeige (R-1066)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.options.test.ts, apps/desktop/ui/src/lib/models/connection.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.server.test.ts, apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @f05c9049 2026-11-05T09:59:19+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T4.verdict.json)
Änderung: Reiter Optionen (SSH: Jump-Host, Weiterleitungen hinzufügen/entfernen, Agent-Forwarding, Kompression, Keepalive; Auth-Art im Reiter Anmeldung) und Anzeige (RDP: Skalierung, Fenstermodus, Größe, Leistung mit „Global“ als Standard; Laufwerke, Audio, Drucker, Gateway, NLA). Leere Werte werden nicht gespeichert. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.options.test.ts src/components/ConnectionEditor.tabs.test.ts src/lib/stores/connections.server.test.ts
Doku: → T8
Abhängt von: T2

### T5 — Server: Sitzungsverlauf, Tabelle und Endpunkte (R-1068)  [x]
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/tests/test_connection_sessions.py, apps/server/tests/test_openapi_snapshot.py, apps/server/app/modules/connections/storage.py, apps/server/alembic/versions/c8e2f4a6b0d1_add_connection_sessions.py, apps/server/tests/test_connections_storage.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b6895401 2026-11-05T10:15:51+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T5.verdict.json)
Änderung: Tabelle `connection_sessions` per Alembic-Revision (FK `ON DELETE CASCADE`, Downgrade entfernt sie); `touch` legt einen Eintrag an (Gerät: Name der Geräteregistrierung, sonst der vom Client gemeldete Hostname) und liefert `sessionId`; `POST /connections/{id}/sessions/{sid}/end`, `GET /connections/{id}/sessions?limit=` (Standard 5); Scope wie die Liste; Einträge älter als 90 Tage löscht der Server beim Schreiben. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connection_sessions.py tests/test_connections_storage.py tests/test_connections_isolation.py tests/test_openapi_snapshot.py tests/test_migrations_smoke.py
Doku: → T8

### T6 — Desktop: Sitzungen schreiben, Ende bei RDP, lokaler Verlauf (R-1068)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/src-tauri/src/connection/sessions.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @9512ee05 2026-11-05T10:25:26+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T6.verdict.json)
Änderung: Lokaler Sitzungsverlauf in `sessions.json` je Workspace (höchstens 50 je Verbindung und 90 Tage) mit den Befehlen `start_session`, `end_session`, `list_sessions(connectionId)` und `device_name`; das Ende einer RDP-Sitzung meldet das Ereignis `rdp-exit` (FreeRDP und mstsc); Bridge-Funktionen und -Typen. Die Verdrahtung im Connect-Flow baut T7.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session
Doku: → T8
Abhängt von: T5

### T7 — Inspector: „Letzte Sitzungen“ (R-1068)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/lib/api/connections.ts, apps/desktop/ui/src/components/AppShell.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ef69ae77 2026-11-05T10:44:37+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T7.verdict.json)
Änderung: Verbinden legt eine Sitzung an (Server-Modus über `touch` mit dem bereinigten Hostnamen als `device`, lokal und Sync über `start_session`), `rdp-exit` beendet sie (Server: `.../sessions/{id}/end`, lokal: `end_session`). Der Inspector lädt die letzten 5 Sitzungen der gewählten Verbindung (Beginn, Dauer oder „—“, Gerät), leerer Zustand „Noch keine Sitzungen“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/ConnectionInspector.test.ts src/lib/stores/connectFlow.test.ts
Doku: → T8
Abhängt von: T6

### T8 — Doku DE+EN und Changelog (R-1066, R-1068)  [x]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-verbindungen-3.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @5ebef869 2026-11-05T10:48:22+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku: Optionen je Verbindung, Verlauf; Hinweis, dass ein alter Client beim Bearbeiten die Optionen verwirft. API-Referenz: `options`, Sitzungs-Endpunkte, Speicherdauer 90 Tage. Entwickler-Doku: Überschreibung der globalen RDP-Werte, lokaler Verlauf (50 je Verbindung). Changelog-Fragment (umlautfrei). `docs/admin/index.html` ändert auch feature/kern-pg-1 (eine Zeile, andere Stelle): vor dieser Task origin/main hineinmergen, falls pg-1 gemergt ist.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts
Doku: diese Task

### T9 — Desktop: gespeichertes RDP-Passwort an Gateway und NLA-Wahl binden (R-1066)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/password.rs, apps/desktop/src-tauri/src/connection/mod.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @8bf817ec 2026-11-05T11:13:20+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T9.verdict.json)
Änderung: Nachtrag aus der Abschlussprüfung. Der Schlüssel des gespeicherten RDP-Passworts trägt Gateway und „NLA aus“, wenn gesetzt (ohne beides bleibt er unverändert); `check_credential_connection` verlangt dieselbe Gateway- und NLA-Wahl bei geöffneter und Quell-Verbindung. Tests: abweichende Wahl ergibt einen anderen Schlüssel und wird abgelehnt, Schlüssel ohne Optionen unverändert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage_key -- stored_password_key -- termsrv_legacy
Doku: keine (internes Verhalten des Passwortspeichers)

### T10 — Doku: Route im Schlüssel des RDP-Passworts DE+EN (R-1066)  [x]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @94b0a363 2026-11-05T11:24:23+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Nachtrag aus der Abschlussprüfung zu T9: Keyring-Account mit `|gw=<gateway>` und `|nla=off`, eine geänderte Route fragt neu; Status und Übernahme der Windows-Alt-Einträge nur ohne Route.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts
Doku: diese Task

### T11 — Desktop: Windows-Test von write_rdp_file mit Optionen-Argument (R-1066)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/rdp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @7ce6a96b 2026-11-05T11:49:55+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T11.verdict.json)
Änderung: Nachtrag aus der PR-CI (#402, Job „Desktop-Backend (cargo test, Windows)“): der Windows-Test `write_rdp_file_reaps_prior_leftovers` ruft `write_rdp_file` ohne das in T3 ergänzte neunte Argument `own`; er übergibt `None`. Lokal nicht baubar (kein Windows-Target), den Beweis trägt der CI-Job.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp
Doku: keine (nur Test)

### T12 — Desktop-UI: Vertrags- und Paritätstests kennen die Optionstypen (R-1066)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @313771c1 2026-11-05T11:51:22+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T12.verdict.json)
Änderung: Nachtrag aus der PR-CI (#402, Job „Desktop-UI“): `types.contract.test.ts` bildet `ConnectionOptions`, `SshOptions`, `SshForward` und `RdpConnectionOptions` (Schema `RdpOptions`) auf die Server-Schemas ab; der TS-Typ `SshForwardType` heißt wie das Rust-Enum `SshForwardKind`, damit `types.parity.test.ts` ihn findet.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/api/types.contract.test.ts -- src/lib/bridge/types.parity.test.ts
Doku: keine (nur Typnamen und Tests)

### T13 — Server: Schlüssel-Matrix und Antwortform für Sitzungen (R-1068)  [x]
Komponente: server · Dateien: apps/server/tests/test_api_key_server_binding.py, apps/server/tests/test_response_shapes.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @26fcc86e 2026-11-05T11:52:08+01:00
Review: approve (.ah-out/review/kern-verbindungen-3/T13.verdict.json)
Änderung: Nachtrag aus der PR-CI (#402, Server-Jobs): die Matrix der Schlüssel-Routen nimmt `GET …/sessions` und `POST …/sessions/{session_id}/end` auf (gebundener Schlüssel nur für Verbindungen seines Servers); `test_response_shapes` erwartet für `touch` `ConnectionTouchOut` und `to_dict()` plus `sessionId` (gewollte Änderung aus T5).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_api_key_server_binding.py -- tests/test_response_shapes.py
Doku: keine (nur Tests)

## Entscheidungen
- T1: Form der Optionen. SSH: `jumpHost` als `[user@]host[:port]`, bis zu acht Hops mit Komma (wie `-J`); `forwards` höchstens 32 Einträge `{type L|R|D, listen "[bind:]port" (bind auch `*`), target "host:port"}`: L/R brauchen ein Ziel, D (SOCKS) nimmt keins; `keepalive` in Sekunden 1–3600 (`ServerAliveInterval`); `authMethod` key|agent|password. RDP: `scalingMode`, `windowMode`, `performanceProfile` mit den Werten der Desktop-Enums, `customSize` im Bereich von `parse_custom_size` (640x480–7680x4320); `drives`, `printers`, `nla` als bool, `audio` local|remote|off, `gateway` `host[:port]`. Host: Name aus `[A-Za-z0-9._-]` ohne führendes `-`, oder IPv6 in Klammern; Port 1–65535 als Regex, damit `0` und `65536` scheitern. Damit sind Leerzeichen, Steuerzeichen und Shell-Zeichen ausgeschlossen.
- T1: Gespeichert wird nur, was gesetzt ist (`_compact` entfernt None rekursiv, leer → NULL), damit „Feld fehlt“ der globale Standard bleibt. `PUT` ersetzt `options` als Ganzes (kein Merge), `null` löscht; ohne `options` im Body bleiben sie. Die Antwort trägt `options` nur, wenn gesetzt, wie `serverId`. `ConnectionOut.options` ist ein `dict`, nicht das Modell: eine Zeile soll die Liste nicht in einen 500 kippen, falls das Schema später strenger wird (wie `tags: Any`). Ein Extra-Eintrag `options` aus `extra_data` (vor der Spalte) wird nie ausgegeben, weil `options` jetzt ein bekanntes Feld ist.
- T2: Schalter nach ssh(1) und ssh_config(5) (OpenSSH 10.0p2): `-J destination` („Connect to the target host by first making an ssh connection to the jump host described by destination“; ProxyJump: „[user@]host[:port] … Multiple proxies may be separated by comma characters“), `-L/-R [bind_address:]port:host:hostport` („an empty address or `*' indicates that the port should be available from all interfaces“), `-D [bind_address:]port`. Booleans über `-o`, damit ein ausdrückliches Aus eine `~/.ssh/config` schlägt: ForwardAgent („Specifies whether the connection to the authentication agent (if any) will be forwarded to the remote machine … no (the default)“), Compression („yes or no (the default)“), ServerAliveInterval (Sekunden). Auth-Art: key → `PreferredAuthentications=publickey` + `IdentitiesOnly=yes` („only use the configured authentication identity and certificate files … even if ssh-agent(1) … offers more identities“), agent → `publickey`, password → `password,keyboard-interactive`. Alles vor `--`.
- T2: `validation.rs` prüft dieselben Formate wie das Server-Schema (Regex wie dort, Längen 1000/300, höchstens 32 Weiterleitungen, Keepalive 1–3600) und vertraut dem Server nicht: lokale Dateien und die Sync-URL gehen nicht durch ihn. Eine Sync-Verbindung mit ungültigen Optionen fällt wie bisher bei ungültigem Host aus der Liste (`sanitize_synced_connections`). Weiterleitungs-Typ und Auth-Art sind geschlossene Enums: Unbekanntes parst nicht. `Connection.options` ist `Option` mit `skip_serializing_if`, alte Dateien laden unverändert. Die TS-Typen stehen in `bridge/types.ts` (Rust-Spiegel) und `api/types.ts` (Server) getrennt, wie die Dateiköpfe es verlangen. Der `Verify:` nimmt zwei libtest-Filter (`-- ssh -- validation`), `cargo test` nimmt nur einen TESTNAME.
- T2: Die übrigen `Connection { … }`-Literale (nur Tests) bekommen `options: None` (Dateiliste per set-files).
- T3: Die Werte der Verbindung gewinnen je Feld über die globalen RDP-Einstellungen (`RdpOptions::with_overrides`); ein ausgelassenes Feld fügt nichts hinzu, es gilt der Default von FreeRDP bzw. mstsc.
- T3: FreeRDP-Schalter aus `client/common/cmdline.h` 2.11.7 und 3.10.3: `+drives`, `/sound`, `/audio-mode:1|2`, `/printer`, `/sec:nla`, `/sec:tls`; Gateway in 3 `/gateway:g:<gateway>[:<port>]` (`/g` nur mit WITH_FREERDP_DEPRECATED_COMMANDLINE), in 2 `/g:`. Die Version liest `--version` („This is FreeRDP version …“, in 3 auch mit „[name] “) und nur bei gesetztem Gateway; `xfreerdp3` gilt ohne Aufruf als 3.
- T3: NLA aus = `/sec:tls`, weil `/sec:nla:off` nur FreeRDP 3 kennt; TLS ohne NLA ist in 2 und 3 dasselbe.
- T3: Mit Gateway entfallen TCP-Preflight und Anmeldeprüfung (beide verbinden direkt, ohne Gateway); mit NLA aus entfällt die Anmeldeprüfung (sie prüfte mit anderer Sicherheitsstufe als der Start). Ob FreeRDP fürs Gateway dieselben Anmeldedaten nimmt: nicht verifiziert.
- T3: mstsc-Zeilen nach MS Learn `IRemoteDesktopClientSettings::SetRdpProperty`: `drivestoredirect`, `audiomode` 0/1/2, `redirectprinters`, `enablecredsspsupport`, `gatewayhostname` mit `gatewayusagemethod:i:1` und `gatewayprofileusagemethod:i:1`. Der Windows-Zweig (`write_rdp_file`) ist lokal nicht baubar (kein Windows-Target); `connection_rdp_lines` läuft im Unix-Test, den Rest prüft der CI-Job „Desktop-Backend (cargo test, Windows)“.
- T3: Gateway-Format wie Jump-Host-Hop ohne Benutzer: `HOST(:PORT)?`, höchstens 300 Zeichen; `customSize` über `rdp_logic::parse_custom_size`, dieselbe Prüfung wie global.
- T2 (Nachtrag aus dem security-Hinweis): OpenSSH V_10_2_P1 baut bei mehreren Hops den ProxyCommand mit `" -J ", options.jump_extra` ungequotet (ssh.c:1356–1367) und führt ihn per `shell -c` aus (sshconnect.c:233–235); `[`/`]` eines IPv6-Hops ab dem zweiten werden so Shell-Glob. Keine Injection (JUMP_RE schließt andere Shell-Zeichen aus); ob IPv6-Literale nur im ersten Hop erlaubt sein sollen, ist eine Frage an Kevin.
- T4: `normalizeConnection` warf `options` bisher weg und `toServerPayload` schickte sie nicht; beide tragen sie jetzt. Der Store schickt `options` immer, als Ganzes oder `null`, weil `PUT` ersetzt und ein fehlendes Feld die alten Optionen behielte. `normalizeOptions` behält nur die Optionen der eigenen Art und streicht Leeres (getrimmte Strings, Weiterleitungen ohne `listen`, `D` ohne Ziel), damit „Global“ wirklich fehlt.
- T4: Der Editor hält SSH- und RDP-Optionen getrennt, damit ein Typwechsel nichts verliert; erst `collect()` behält die der gespeicherten Art. Tri-State-Auswahl Global/An/Aus statt Checkbox, weil ein ausdrückliches Aus (`ForwardAgent=no`) etwas anderes ist als „nicht gesetzt“. Die Anzeige-Felder nutzen die Texte der globalen RDP-Einstellungen (`settings.rdp.*`).
- T4: Die UI prüft Keepalive 1–3600, Ziel bei L/R und die Größe mit `RDP_CUSTOM_SIZE_PATTERN` wie die globale Einstellung; Jump-Host- und Gateway-Format prüfen Rust und Server (eine dritte Regex-Kopie im UI wäre nur Drift). Die Bereichsgrenze 640x480 der Größe prüft wie global erst Rust.
- T5: Gerät = der vom Client gemeldete Hostname (`device` im optionalen Touch-Body, ohne Steuerzeichen, 1–255 Zeichen). Die Geräteregistrierung (`DeviceLine`) trägt keinen Namen (nur Art, ID, Zeiten), und der Zertifikats-CN ist der Benutzername: Einen Registrierungsnamen gibt es also noch nicht, „sonst Hostname“ ist damit der einzige Weg. Ohne Body bleibt `device` leer (alte Clients).
- T5: Ein Touch ohne Body bleibt gültig (`TouchRequest` optional), die Antwort ist `ConnectionOut` plus `sessionId`. Zeiten speichert die Tabelle naiv in UTC (F7), die API gibt sie mit `+00:00` aus wie `lastUsed`.
- T5: Beenden darf nur der Nutzer, der die Sitzung begann (gleiche `user_id`); eine Sitzung ohne Nutzer (API-Key, gelöschter Nutzer) beendet niemand, sie bleibt ohne Ende. Zweites Beenden behält das erste Ende. Die Liste zeigt im Scope der Verbindung die Sitzungen aller Nutzer, `limit` 1–50, Standard 5.
- T5: Die 90 Tage setzt der Touch durch (löscht alle älteren Einträge aller Verbindungen), die Liste blendet Ältere bis dahin aus; kein Scheduler-Job. `user_id` ist `ON DELETE SET NULL`, damit ein gelöschter Nutzer den Verlauf nicht mitnimmt.
- T5: `save_connections` (Hooks) prüft `options` mit `ConnectionOptions` wie die API und speichert die geprüfte Form (`"30"` wird 30, `"yes"` true), sonst verwürfe der Desktop die Verbindung; ein ungültiger Wert schreibt nichts (ValidationError vor der Sitzung).
- T6: Schnitt Rust/UI: T6 baut die Rust-Seite (lokaler Verlauf `sessions.json` je Workspace in `connection/sessions.rs`, Befehle `start_session`/`end_session`/`list_sessions`/`device_name`, Ereignis `rdp-exit` mit der `correlationId`) und die Bridge; das Verdrahten im Connect-Flow (Touch mit `device`, Ende auf `rdp-exit`, Server- oder lokaler Weg je Modus) geht mit dem Inspector in T7, denn `touch` ruft schon heute die UI (`connectFlow.ts`), und Rust kennt die `sessionId` der Server-Sitzung nicht. `sync.rs` bleibt unverändert.
- T6: Lokal gilt dieselbe Regel wie am Server: 90 Tage und höchstens 50 je Verbindung, beim Schreiben beschnitten, beim Lesen ausgeblendet; zweites Ende behält das erste, eine unbekannte ID ist kein Fehler (die Speicherdauer kann sie während der Sitzung genommen haben). Ein kaputtes `sessions.json` ist ein Fehler und wird nicht überschrieben. Ein Mutex im Prozess hält zwei gleichzeitige Verbindungen vom gegenseitigen Überschreiben ab; Sitzungs-ID aus Zeit, PID und Zähler (kein uuid-Crate im Desktop).
- T6: Hostname über `/proc/sys/kernel/hostname` (Linux), sonst `COMPUTERNAME`/`HOSTNAME`, sonst `hostname`. `rdp-exit` feuert bei jedem Ende des FreeRDP-Prozesses (mit und ohne Passwort) und unter Windows beim Ende des gestarteten `mstsc`; der Windows-Zweig ist lokal nicht baubar (kein Windows-Target), ihn prüft der CI-Job „Desktop-Backend (cargo test, Windows)“. SSH und Web haben kein Ende („—“, Nicht-Ziel).
- T7: Die Sitzung beginnt dort, wo heute `lastUsed` gesetzt wird (`markConnectionUsed`): Server per `touch` mit `device`, lokal und Sync per `start_session`. Das Ende kennt nur RDP: `rdp-exit` beendet die Sitzung seines Starts (Map `correlationId` → Promise der Sitzung, denn ein sofort endender Start kann sein Ende melden, bevor die Sitzung geschrieben ist); scheitert der Start, endet die Sitzung sofort. Fehler beim Schreiben oder Beenden einer Sitzung melden nichts und brechen das Verbinden nicht ab: der Verlauf zeigt die Sitzung dann ohne Ende bzw. gar nicht.
- T7: Der Hostname geht ohne Steuerzeichen, getrimmt und auf 255 Zeichen gekürzt an den Server (er lehnt Steuerzeichen mit 422 ab, und jeder Touch schlüge fehl); leer → ohne `device`. Je Prozess einmal gelesen.
- T7: Der Inspector lädt seine Sitzungen selbst (`recentSessions` im Connections-Store, modusabhängig) und neu, sobald `connectFlow` eine Sitzung geschrieben oder beendet hat (Signal `sessionsVersion` im Connections-Store; `lastUsed` reicht nicht: das Ende ändert es nicht, und lokal steht es vor der Sitzung); ein Ladefehler zeigt „Sitzungen konnten nicht geladen werden“ statt eines leeren Verlaufs. Beginn relativ (`timeAgo`, genaue Zeit im `title`), Dauer „< 1 min“/„N min“/„H h M min“, offen oder unbekannt „—“.
- T9: Die Route (Gateway getrimmt und klein, „NLA aus“) gehört zum Schlüssel des gespeicherten RDP-Passworts (`password::rdp_route`), nur wenn gesetzt: Schlüssel ohne Gateway und mit NLA an oder ungesetzt bleiben, wie sie sind, keine Migration. Eine geänderte Route fragt das Passwort neu ab, wie ein geänderter Host. `check_credential_connection` verlangt dieselbe Route bei geöffneter und Quell-Verbindung, weil der Start Gateway und NLA aus der geöffneten nimmt, den Schlüssel aber aus der Quelle. Der Altschlüssel (`rdp|<ziel>`) trägt die Route mit; Gateway-Verbindungen gibt es erst seit T3, also keine alten Einträge mit Route.
- T9 (Nachtrag aus security): Unter Windows übernimmt der Start einen alten `TERMSRV/<host:port>`-Eintrag (vor R-0431) nur ohne Route (`readable_legacy_termsrv`): der Eintrag nennt keine Route, sein Passwort galt dem direkten Weg.
