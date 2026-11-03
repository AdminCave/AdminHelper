<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-1 — Task-Ledger
Status: erledigt · Branch: feature/kern-verbindungen-1 · Review: pro Task
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

### T4 — Stores: Favoriten und Ping-Werte  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/bridge/types.parity.test.ts, apps/desktop/ui/src/lib/stores/session.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e27095fb 2026-11-02T23:10:21+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T4.verdict.json)
Änderung: `favoriteConnections` im Settings-Typ, `toggleFavorite(id)` speichert über die Settings; Store `reachability` (id → ms | null | 'tunnel'), `probeVisible(conns)` ruft `probeTargets` für Verbindungen ohne Tunnel (Web: Host/Port aus der URL), Intervall 60 s nur bei sichtbarer Seite. Tests mit gemockter Bridge. Abhängt von T2, T3. R-1065, R-1067.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connections.test.ts src/lib/stores/session.test.ts src/lib/bridge/types.parity.test.ts
Doku: → T9
Abhängt von: T2, T3

### T5 — Verbindungsseite: Leiste, Werkzeugleiste, Tabelle/Karten, Gruppen, Schnellzugriff  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/pages/Connections.test.ts, apps/desktop/ui/src/pages/Connections.load.test.ts, apps/desktop/ui/src/components/connections/ConnectionSidebar.svelte, apps/desktop/ui/src/components/connections/ConnectionTable.svelte, apps/desktop/ui/src/components/connections/QuickAccess.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.shell.test.ts, apps/desktop/ui/src/styles/app.css
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a8bbf030 2026-11-02T23:37:29+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T5.verdict.json)
Änderung: Umbau nach Mockup mit `components/ui/` (SPDX bei neuen Dateien): Leiste ab 1180 px (Bibliothek, Typ, Ordner mit Zählern), Suche und Filter-Chips mit „Zurücksetzen“, Ansicht Tabelle/Karten, Gruppierung (Server/Ordner/Typ/keine) einklappbar, sortierbare Spalten Name/Ping/Zuletzt, Stern, Schnellzugriff; ersetzt die Chips single/grouped und die Baumansicht. Einfachklick wählt, Doppelklick verbindet. Stabile Selektoren für E2E (`data-testid="conn-row"`, `.conn-name`). Komponententests. Mehr als acht Dateien nur durch die Teilung in Bausteine. Abhängt von T1, T4. R-1065, R-1067.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Connections.test.ts src/pages/Connections.load.test.ts src/lib/i18n/i18n.test.ts src/components/AppShell.shell.test.ts
Doku: → T9
Abhängt von: T1, T4

### T6 — Inspector und Tastatur  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/pages/Connections.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/connections/ConnectionTable.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @bac68d82 2026-11-02T23:51:56+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T6.verdict.json)
Änderung: Inspector ab 900 px für die gewählte Verbindung (Felder laut Spec, Erreichbar, Kommando-Vorschau mit Kopieren, Notizen; Verbinden, Bearbeiten, Favorit); ↑/↓ wählt, ↵ verbindet, Esc hebt die Auswahl auf. Tests. Abhängt von T5. R-1065, R-1067.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/ConnectionInspector.test.ts src/pages/Connections.test.ts
Doku: → T9
Abhängt von: T5

### T7 — Mehrfachauswahl und Sammelaktionen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/BulkBar.svelte, apps/desktop/ui/src/components/connections/BulkBar.test.ts, apps/desktop/ui/src/components/connections/ConnectionTable.svelte, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Connections.test.ts, apps/desktop/ui/src/lib/charts.ts, apps/desktop/ui/src/lib/models/connectionList.ts, apps/desktop/ui/src/lib/models/connectionList.test.ts, apps/desktop/ui/src/components/connections/ConnectionInspector.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @bb056cb2 2026-11-03T00:07:44+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T7.verdict.json)
Änderung: Checkboxen je Zeile und „alle sichtbaren“; Leiste mit Tags hinzufügen/entfernen (über `upsert`), Exportieren als CSV (Name, Typ, Host, Port, Benutzer, URL, Tags; Speichern-Dialog und `write_export_csv` aus kern-monitoring-3, CSV-Zellen wie dort geschützt), Löschen mit Bestätigung (über `remove`). Tests. Abhängt von T5 und dem Merge von kern-monitoring-3. R-1065.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/connections/BulkBar.test.ts src/pages/Connections.test.ts src/components/connections/ConnectionInspector.test.ts src/lib/models/connectionList.test.ts src/lib/charts.test.ts src/lib/i18n
Doku: → T9
Abhängt von: T5

### T8 — Desktop-E2E auf die neue Liste  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/ssh-connect.live.js, apps/desktop/e2e/test/specs/rdp-connect.live.js, apps/desktop/e2e/test/specs/web-connect.live.js, apps/desktop/e2e/test/specs/tunnel-connect.live.js, apps/desktop/e2e/test/specs/connection-editor.live.js, apps/desktop/e2e/test/specs/two-installations.workspaces.js, apps/desktop/e2e/test/lib/live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @a6917474 2026-11-03T00:12:39+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T8.verdict.json)
Änderung: Die Specs wählen eine Verbindung über `[data-testid="conn-row"]`/`.conn-name` und verbinden per Doppelklick statt Einfachklick auf `.card`. Lokal nur Lint; der Beweis ist der Sammellauf (Heavy). Abhängt von T5, T6.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testcode)
Abhängt von: T6

### T9 — Doku: Verbindungsliste und probe_targets  [x]
Komponente: scripts · Dateien: docs/index.html, docs/en/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-verbindungen-1.md, docs/admin/index.html, docs/en/admin/index.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c9e8b0e9 2026-11-03T00:30:55+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Bedienung der Verbindungsliste (Leiste, Favoriten lokal je Workspace, Schnellzugriff, Tastatur, Sammelaktionen, Erreichbarkeit vom Gerät) an der maßgeblichen Stelle DE+EN (Ort beim Bauen per grep festlegen), Befehl `probe_targets` in der Befehlstabelle, CHANGELOG-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

### T10 — Abschlussprüfung: Pfeiltasten bei doppelten Zeilen, Anker für „Neu“, eigene Waisen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/connections/ConnectionTable.svelte, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/pages/Connections.test.ts, apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.test.ts, apps/desktop/ui/src/lib/models/connection.ts, apps/desktop/ui/src/styles/app.css
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @bddd214d 2026-11-03T00:54:30+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T10.verdict.json)
Änderung: ↑/↓ gehen von der fokussierten Zeile aus (`document.activeElement`), nur ohne Zeilenfokus von `selectedId`; so erreicht die Tastatur bei Gruppierung nach Ordner auch die Zeilen nach einer doppelt gelisteten Verbindung (Test in `Connections.test.ts`). Der Knopf „Neue Verbindung“ bekommt `data-action="connection-new"` als E2E-Anker. Eigene Waisen seit T5 raus: Store-Exporte `kindFilter`, `groupFilter`, `viewMode`, `filteredConnections`, `groupedConnections` samt Typen, `groupConnectionsByHost`/`groupedTagKeys`/`ConnectionGroup` in `models/connection.ts`, die CSS-Regeln der alten Seite ohne Nutzer (`.toolbar-left/-right`, `.tree*`, `.card-main/-title/-meta/-tag/-tags`, `.tunnel-badge`, nach grep).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Connections.test.ts src/lib/stores/connections.test.ts src/components/connections
Doku: keine (Fehlerbehebung und Aufräumen ohne dokumentierte Änderung)
Test-Löschung: apps/desktop/ui/src/lib/stores/connections.test.ts::filteredConnections (derived) — der Store-Export ist seit T5 ohne Nutzer und fällt weg, die Filterlogik testet `connectionList.test.ts`; apps/desktop/ui/src/lib/stores/connections.test.ts::groupedConnections (derived) — ebenso, die Gruppierung testet `connectionList.test.ts`

### T11 — Abschlussprüfung: connection-editor-Spec auf den neuen Knopf, Spec-Begründung der Probe  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/connection-editor.live.js, docs/features/kern-verbindungen-1.md
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @617e780d 2026-11-03T00:56:16+01:00
Review: approve (.ah-out/review/kern-verbindungen-1/T11.verdict.json)
Änderung: Der Spec öffnet den Editor über `[data-action="connection-new"]` statt `.toolbar-right .btn.primary`. In der Spec (Trade-offs) die falsche Begründung „ein Webview kann ohnehin fetch absetzen“ ersetzen: die CSP erlaubt `connect-src` nur `'self'`/IPC, `probe_targets` gibt einem kompromittierten Webview also erstmals TCP-Connects mit lesbarer Latenz; Voraussetzung bleibt XSS (Security-Nit der Abschlussprüfung).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testcode und Spec)
Abhängt von: T10

## Entscheidungen
- 2026-11-02: Favoriten lokal in den Settings je Workspace, Erreichbarkeit per TCP-Probe vom Gerät (Spec, Trade-offs); beide Zeilen überlassen die Wahl dem Plan.
- 2026-11-02: Ohne „Verbunden“, „In Tabs öffnen“ und Split-Button: hängen an eingebetteten Sitzungen (R-1069/R-1070).
- 2026-11-02: T2: Favoriten in `Meta` (je Workspace), nicht in `Prefs` (geräteweit, alle Workspaces); `Settings` ist das Bridge-Struct, deshalb ziehen `bridge/types.ts` und die UI-Defaults in T2 mit (Paritätstest), die Stores bleiben T4. Mehr als acht Dateien nur durch die Pflicht-Initialisierer der Meta-Literale.
- 2026-11-02: overlap.sh: kern-monitoring-3 ändert commands.rs, main.rs, bridge/index.ts, dictionaries.ts; T3 und T7 erst nach dessen Merge, davor `git merge origin/main`.
- 2026-11-02: T4: `ProbeTarget` (probe.rs, T3) kreuzt die Bridge, deshalb probe.rs in die Scan-Liste des Paritätstests und der Typ nach `bridge/types.ts`; Verify zusätzlich mit `types.parity.test.ts` gefahren. Favoriten speichert `setFavoriteConnections` in `stores/session.ts` (wie `setAllowSelfSignedCerts`), Toggles laufen nacheinander. Gleiche Host/Port-Ziele werden einmal geprobt; Verbindungen ohne Ziel bleiben unbekannt, nicht `null`.
- 2026-11-02: T5: Layout per CSS-Container-Query (Leiste ab 1180 px Seitenbreite, kompakte Tabelle unter 820 px Listenbreite), nicht per gemessener Breite: jsdom misst 0, der Zustand bliebe ungetestet und die Seite bräuchte einen ResizeObserver. Filter, Sortierung, Gruppierung und Ansicht sind Seitenzustand (wie im Mockup), die alten Store-Exporte `kindFilter`, `groupFilter`, `viewMode`, `filteredConnections`, `groupedConnections` nutzt danach nur noch `connections.test.ts`; sie bleiben, weil `connections.ts` nicht zu T5 gehört (Fund für die Abschlussprüfung). Mehrfachauswahl (Checkboxen) kommt mit T7. Ungenutzte Schlüssel `filters.single/grouped`, `view.list/tree`, `tree.*`, `grouped.connections` raus.
- 2026-11-02: T6: Inspector ab 900 px Seitenbreite (340 px, ab 1380 px 380 px) per Container-Query wie T5. Tastatur am Listbox der Tabelle (`ConnectionTable.svelte` in die Dateien): ↑/↓ gehen über die Zeilen in DOM-Reihenfolge (eingeklappte Gruppen fallen weg) und fokussieren sie, ↵ verbindet weiter über die Zeile, Esc hebt die Auswahl auf. „Server“ zeigt nur einen Namen, den das Inventar (`infraServers`) schon hält; die Seite lädt das Inventar nicht nach. Notizen sind die der Verbindung (das Mockup zeigte Server-Notizen).
- 2026-11-03: T7: Auswahl als `SvelteSet` der IDs im Seitenzustand, die ausgewählten Verbindungen aus dem Store abgeleitet (gelöschte fallen heraus). „Alle sichtbaren“ wirkt auf die gefilterte Liste. Sammelaktionen laufen nacheinander über `upsert`/`remove` (wie der Editor, je Modus: Server-API, lokale Datei, Sync nur im Speicher); Tags ändern nur Verbindungen, bei denen sich etwas ändert; beim Löschen das RDP-Passwort wie im Editor (Fehler nicht fatal). Klick auf die Checkbox wählt die Zeile nicht und verbindet nicht. Verify zusätzlich mit Inspector-, Listenmodell-, CSV- und i18n-Tests (Nit aus T6 in `ConnectionInspector.test.ts`, `csvCell` aus `charts.ts` exportiert).
- 2026-11-03: T8: Der Doppelklick wird wie `jsClick` im Webview ausgelöst (`dblclick`, bubbles, für Sveltes Delegation), nicht über WebKitWebDriver-Pointer-Aktionen; Helfer `connectByName` und `CONN_ROW` in `test/lib/live.js` (deshalb in den Dateien), die Multiremote-Spec trägt beides inline. Die Nits des T7-Prüfers (Kommas im Bulk-Tag-Feld, Leerzeichen als Tag-Trenner im CSV) gehen an die Abschlussprüfung.
