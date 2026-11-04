<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-verbindungen-2 · Review: pro Task
Spec: docs/features/kern-verbindungen-2.md (Roadmap R-1066, R-1068)
Heavy: linux-full — Desktop-Journey Verbindungen (Editor); der Sammellauf fährt die GUI-E2E
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Vorlage `AdminCave/DesignSystem@244e890` (`ui_kits/adminhelper/editor.jsx`, `connections.jsx`). Stand `origin/main@c550f4a9`. Gebaut nach dem Merge von kern-notify-1 (gemeinsam: `apps/desktop/ui/src/lib/i18n/dictionaries.ts`).

### T1 — Server: Feld `options` an der Verbindung (R-1066)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Datenmodell options, Q1))
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/alembic/versions/, apps/server/tests/test_connections_options.py, apps/server/tests/test_openapi_snapshot.py
Änderung: Pydantic `ConnectionOptions` (`ssh`: jumpHost, forwards[{type L/R/D, listen, target}], agentForwarding, compression, keepalive, authMethod; `rdp`: scalingMode, windowMode, customSize, performanceProfile, drives, audio, printers, gateway, nla), alle optional, `extra="forbid"`, Formate an der Grenze geprüft. Spalte `options` per Alembic-Revision, in Create/Update/Out, Import und Export. Neue Testdatei mit SPDX; OpenAPI-Snapshot nachziehen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connections_options.py tests/test_openapi_snapshot.py
Doku: → T9

### T2 — Desktop: SSH-Optionen in Modell, Validierung und Startargumenten (R-1066)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Datenmodell options, Q1))
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/api/types.ts
Änderung: `Connection.options` (`#[serde(default)]`), Validierung (Host[:Port] mit optionalem Benutzer, Ports 1–65535, kein führendes `-`, keine Steuerzeichen), `build_ssh_args` setzt `-J`, `-L/-R/-D`, `-A`, `-C`, `-o ServerAliveInterval=30`, Auth-Art über `-o PreferredAuthentications`/`IdentitiesOnly`. Schalter vorher in `ssh(1)` nachlesen. Tests mit bösen Werten.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ssh validation
Doku: → T9
Abhängt von: T1

### T3 — Desktop: RDP-Optionen je Verbindung, Linux-Argumente und .rdp-Datei (R-1066)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Datenmodell options, Q1))
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/validation.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/connection/mod.rs
Änderung: Die RDP-Optionen der Verbindung überschreiben `RdpOptions` aus den Settings Feld für Feld; dazu `/drive`, `/sound`, `/printer`, `/gateway`, `/sec:nla` (FreeRDP) und die passenden Zeilen in `write_rdp_file` (Windows). Schalter vorher im FreeRDP-Wiki und in Microsofts „Supported RDP properties“ nachlesen. Tests je Plattformzweig.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- rdp
Doku: → T9
Abhängt von: T2

### T4 — Editor v2: Typ-Umschalter, Tabs und „Server zuordnen“ (R-1066)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @aa2697b9 2026-11-04T20:10:59+01:00
Review: approve (.ah-out/review/kern-verbindungen-2/T4.verdict.json)
Änderung: Editor mit Typ-Umschalter und Tabs (SSH Allgemein/Anmeldung/Optionen, RDP Allgemein/Anmeldung/Anzeige, Web nur Allgemein); die heutigen Felder auf die Tabs verteilt; „Server zuordnen“ als Auswahl der Server (nur Server-Modus, setzt `serverId`). Die Tabs Optionen/Anzeige bleiben bis T5 leer verborgen. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts src/components/ConnectionEditor.delete.test.ts src/components/ConnectionEditor.lastused.test.ts
Doku: → T9

### T5 — Editor v2: Optionen und Anzeige (R-1066)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Datenmodell options, Q1))
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.options.test.ts, apps/desktop/ui/src/lib/models/connection.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Tab Optionen (SSH: Jump-Host, Weiterleitungen hinzufügen/entfernen, Agent-Forwarding, Kompression, Keepalive; Auth-Art im Tab Anmeldung) und Anzeige (RDP: Skalierung, Fenstermodus, Größe, Leistung mit „Global“ als Standard; Laufwerke, Audio, Drucker, Gateway, NLA). Leere Werte werden nicht gespeichert. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.options.test.ts
Doku: → T9
Abhängt von: T2, T4

### T6 — Server: Sitzungsverlauf, Tabelle und Endpunkte (R-1068)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Sitzungsverlauf/Speicherdauer, Q2/Q3))
Komponente: server · Dateien: apps/server/app/modules/connections/models.py, apps/server/app/modules/connections/schemas.py, apps/server/app/modules/connections/router.py, apps/server/alembic/versions/, apps/server/tests/test_connection_sessions.py, apps/server/tests/test_openapi_snapshot.py
Änderung: Tabelle `connection_sessions` per Alembic-Revision; `touch` legt einen Eintrag an und liefert `sessionId`; `POST /connections/{id}/sessions/{sid}/end`, `GET /connections/{id}/sessions?limit=`; Scope wie die Liste; Löschen nach der Speicherdauer. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_connection_sessions.py tests/test_openapi_snapshot.py
Doku: → T9

### T7 — Desktop: Sitzungen schreiben, Ende bei RDP, lokaler Verlauf (R-1068)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Sitzungsverlauf/Speicherdauer, Q2/Q3))
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/mod.rs, apps/desktop/src-tauri/src/connection/rdp.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/sync.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts
Änderung: Verbinden legt eine Sitzung an (Server-Modus über `touch`, lokal in `sessions.json` je Workspace mit Kappung), das Ende meldet der RDP-Exit-Monitor; neuer Befehl `list_sessions(connectionId)`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session
Doku: → T9
Abhängt von: T6

### T8 — Inspector: „Letzte Sitzungen“ (R-1068)  [~] (verschoben in kern-verbindungen-3: wartet auf Kevin (Sitzungsverlauf/Speicherdauer, Q2/Q3))
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Der Inspector lädt die letzten 5 Sitzungen der gewählten Verbindung (Beginn, Dauer oder „—“, Gerät), leerer Zustand „Noch keine Sitzungen“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/ConnectionInspector.test.ts
Doku: → T9
Abhängt von: T7

### T9 — Doku DE+EN und Changelog (R-1066, R-1068)  [x]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-verbindungen-2.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @3c011b27 2026-11-04T20:12:33+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Admin-Doku: Editor-Tabs, Optionen je Verbindung, Verlauf; Hinweis, dass ein alter Client beim Bearbeiten die Optionen verwirft. API-Referenz: `options`, Sitzungs-Endpunkte, Speicherdauer. Entwickler-Doku: Überschreibung der globalen RDP-Werte, lokaler Verlauf. Changelog-Fragment.
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts
Doku: diese Task

### T10 — „Server zuordnen“ nur für Admins, Doku zu „Unbekannter Server“ (R-1066)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts, docs/admin/index.html, docs/en/admin/index.html
Änderung: Fund der Abschlussprüfung: `GET /api/servers` verlangt Admin, der Editor lud die Liste auch für Nicht-Admins (403, Fehlerhinweis bei jedem Öffnen); Feld und Laden nur mit `isAdmin`, Test für Nicht-Admin. Doku und Kommentar: der Server setzt `server_id` beim Löschen auf NULL, „Unbekannter Server“ heißt, die Serverliste kennt die ID nicht (fehlt oder nicht geladen).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts src/components/ConnectionEditor.delete.test.ts src/components/ConnectionEditor.lastused.test.ts
Doku: docs/admin/index.html, docs/en/admin/index.html

## Entscheidungen
- T4: Typ-Umschalter `Segmented`, Tabs `Tabs` (Web ohne Tab-Leiste); ein Typwechsel und jedes Öffnen setzen auf Allgemein zurück. „Server zuordnen“ nur bei `mode === 'server'` mit Sitzung; leere Serverliste → `loadServers()` beim Öffnen, die Liste liest der Effect untracked (`get`), sonst startet jede Antwort ihn neu; eine `serverId` ohne bekannten Server bleibt als „Unbekannter Server“ wählbar (sonst verlöre Speichern sie still). Name und Host bleiben die ersten Text-Inputs (Live-E2E `connection-crud`). Der Platz neben Name bleibt außerhalb des Server-Modus leer (Raster wie im Mockup).
- T9: Doku nur für das Gebaute (Editor-Reiter, Server zuordnen) in der Admin-Doku DE+EN und das Fragment; API-Referenz und Entwickler-Doku zu `options` und Sitzungen ziehen mit T1–T3, T5–T8 in den nächsten Zug.
