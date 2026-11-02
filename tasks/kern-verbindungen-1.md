<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-verbindungen-1 · Review: pro Task
Spec: docs/features/kern-verbindungen-1.md (Roadmap R-1065, R-1067)
Heavy: linux-full — Umbau der Verbindungsseite und neuer Tauri-Befehl; die Desktop-Journeys (ssh/rdp/web/tunnel-connect, connection-editor, two-installations) laufen im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Listenlogik: Filter, Sortierung, Gruppierung, Schnellzugriff, Kommando-Vorschau  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/connectionList.ts, apps/desktop/ui/src/lib/models/connectionList.test.ts, apps/desktop/ui/src/lib/models/connection.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a7d47810 2026-11-02T22:12:44+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T1.verdict.json)
Änderung: Neue reine Funktionen (SPDX-Header): Bibliothek (alle, favoriten, recent24h, tunnel), Typ, Ordner (Tag), Suche, Zähler je Eintrag; Sortierung nach Name, Ping, Zuletzt (auf-/absteigend); Gruppierung host/tag/kind/none; Schnellzugriff (Favoriten, dann zuletzt genutzt, höchstens 4); Kommando-Vorschau je Typ (ssh, xfreerdp, URL). R-1065.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/connectionList.test.ts
Doku: → T9

### T2 — Favoriten in den Settings  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/migration.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/models/settings.ts
Evidenz: run.sh[quick] desktop-rs desktop-ui: 2 passed, 0 failed, 16 skipped @4616c120 2026-11-02T22:37:20+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T2.verdict.json)
Änderung: `Settings.favorite_connections: Vec<String>` mit `#[serde(default)]` (Wire `favoriteConnections`), gespeichert in der Meta des Workspace (`workspace.json`), nicht in den geräteweiten Prefs; die Struct-Literale von `Meta` ziehen mit, der Bridge-Typ und die Defaults der UI auch (Paritätstest). Test: eine Meta ohne das Feld lädt mit leerer Liste, Round-Trip behält die IDs, ein anderer Workspace sieht sie nicht. R-1065.
Verify: bash scripts/dev/verify.sh desktop-rs desktop-ui --strict
Doku: → T9

### T3 — Erreichbarkeit: Tauri-Befehl probe_targets  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/probe.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @d18a4fb5 2026-11-02T22:59:55+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T3.verdict.json)
Änderung: Neues Modul (SPDX-Header): TCP-Connect je `{host, port}`, Zeitlimit 1,5 s inkl. DNS, höchstens 16 gleichzeitig, höchstens 256 Ziele (sonst Validierungsfehler), Ergebnis Latenz in ms oder `null`; Befehl registrieren. Tests: lokaler Listener → Wert, geschlossener Port → `null`, 257 Ziele → Fehler, Port 0 → Fehler. Erst nach dem Merge von kern-monitoring-3 bauen (dieselben Dateien commands.rs/main.rs). R-1067.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- probe
Doku: → T9

### T4 — Stores: Favoriten und Ping-Werte  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts
Änderung: `favoriteConnections` im Settings-Typ, `toggleFavorite(id)` speichert über die Settings; Store `reachability` (id → ms | null | 'tunnel'), `probeVisible(conns)` ruft `probeTargets` für Verbindungen ohne Tunnel (Web: Host/Port aus der URL), Intervall 60 s nur bei sichtbarer Seite. Tests mit gemockter Bridge. Abhängt von T2, T3. R-1065, R-1067.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connections.test.ts
Doku: → T9
Abhängt von: T2, T3

### T5 — Verbindungsseite: Leiste, Werkzeugleiste, Tabelle/Karten, Gruppen, Schnellzugriff  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/pages/Connections.test.ts, apps/desktop/ui/src/pages/Connections.load.test.ts, apps/desktop/ui/src/components/connections/ConnectionSidebar.svelte, apps/desktop/ui/src/components/connections/ConnectionTable.svelte, apps/desktop/ui/src/components/connections/QuickAccess.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts
Änderung: Umbau nach Mockup mit `components/ui/` (SPDX bei neuen Dateien): Leiste ab 1180 px (Bibliothek, Typ, Ordner mit Zählern), Suche und Filter-Chips mit „Zurücksetzen“, Ansicht Tabelle/Karten, Gruppierung (Server/Ordner/Typ/keine) einklappbar, sortierbare Spalten Name/Ping/Zuletzt, Stern, Schnellzugriff; ersetzt die Chips single/grouped und die Baumansicht. Einfachklick wählt, Doppelklick verbindet. Stabile Selektoren für E2E (`data-testid="conn-row"`, `.conn-name`). Komponententests. Mehr als acht Dateien nur durch die Teilung in Bausteine. Abhängt von T1, T4. R-1065, R-1067.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Connections.test.ts src/pages/Connections.load.test.ts src/lib/i18n/i18n.test.ts
Doku: → T9
Abhängt von: T1, T4

### T6 — Inspector und Tastatur  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/pages/Connections.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Inspector ab 900 px für die gewählte Verbindung (Felder laut Spec, Erreichbar, Kommando-Vorschau mit Kopieren, Notizen; Verbinden, Bearbeiten, Favorit); ↑/↓ wählt, ↵ verbindet, Esc hebt die Auswahl auf. Tests. Abhängt von T5. R-1065, R-1067.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/ConnectionInspector.test.ts src/pages/Connections.test.ts
Doku: → T9
Abhängt von: T5

### T7 — Mehrfachauswahl und Sammelaktionen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/BulkBar.svelte, apps/desktop/ui/src/components/connections/BulkBar.test.ts, apps/desktop/ui/src/components/connections/ConnectionTable.svelte, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Checkboxen je Zeile und „alle sichtbaren“; Leiste mit Tags hinzufügen/entfernen (über `upsert`), Exportieren als CSV (Name, Typ, Host, Port, Benutzer, URL, Tags; Speichern-Dialog und `write_export_csv` aus kern-monitoring-3, CSV-Zellen wie dort geschützt), Löschen mit Bestätigung (über `remove`). Tests. Abhängt von T5 und dem Merge von kern-monitoring-3. R-1065.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/BulkBar.test.ts src/pages/Connections.test.ts
Doku: → T9
Abhängt von: T5

### T8 — Desktop-E2E auf die neue Liste  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/ssh-connect.live.js, apps/desktop/e2e/test/specs/rdp-connect.live.js, apps/desktop/e2e/test/specs/web-connect.live.js, apps/desktop/e2e/test/specs/tunnel-connect.live.js, apps/desktop/e2e/test/specs/connection-editor.live.js, apps/desktop/e2e/test/specs/two-installations.workspaces.js
Änderung: Die Specs wählen eine Verbindung über `[data-testid="conn-row"]`/`.conn-name` und verbinden per Doppelklick statt Einfachklick auf `.card`. Lokal nur Lint; der Beweis ist der Sammellauf (Heavy). Abhängt von T5, T6.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testcode)
Abhängt von: T6

### T9 — Doku: Verbindungsliste und probe_targets  [ ]
Komponente: scripts · Dateien: docs/index.html, docs/en/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-verbindungen-1.md
Änderung: Bedienung der Verbindungsliste (Leiste, Favoriten lokal je Workspace, Schnellzugriff, Tastatur, Sammelaktionen, Erreichbarkeit vom Gerät) an der maßgeblichen Stelle DE+EN (Ort beim Bauen per grep festlegen), Befehl `probe_targets` in der Befehlstabelle, CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- 2026-11-02: Favoriten lokal in den Settings je Workspace, Erreichbarkeit per TCP-Probe vom Gerät (Spec, Trade-offs); beide Zeilen überlassen die Wahl dem Plan.
- 2026-11-02: Ohne „Verbunden“, „In Tabs öffnen“ und Split-Button: hängen an eingebetteten Sitzungen (R-1069/R-1070).
- 2026-11-02: T2: Favoriten in `Meta` (je Workspace), nicht in `Prefs` (geräteweit, alle Workspaces); `Settings` ist das Bridge-Struct, deshalb ziehen `bridge/types.ts` und die UI-Defaults in T2 mit (Paritätstest), die Stores bleiben T4. Mehr als acht Dateien nur durch die Pflicht-Initialisierer der Meta-Literale.
- 2026-11-02: overlap.sh: kern-monitoring-3 ändert commands.rs, main.rs, bridge/index.ts, dictionaries.ts; T3 und T7 erst nach dessen Merge, davor `git merge origin/main`.
