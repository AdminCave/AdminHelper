<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-UI: Ladefehler der Verbindungsliste, RDP-Bildschirmdaten, Sprachwahl, Löschen mit Rückfrage, Benachrichtigungs-Neustart, Visitor-Port-Prüfung — Task-Ledger
Status: erledigt · Branch: feature/desktop-ui-fixes · Review: pro Task
Spec: docs/features/desktop-ui-fixes.md (Roadmap R-0658, R-0659, R-0660, R-0661, R-0663, R-0585)
Heavy: linux-full — T4 ändert die Argumente des RDP-Starts (`client` für `open_connection`/`open_connection_stored`, daraus `/size` und `/scale` von xfreerdp3), die nur der RDP-Start der GUI-E2E im Sammellauf mit echter Anzeige fährt (`scripts/tests/desktop_e2e_connect.sh`, `rdp-connect.live.js`); T10 ändert die Prüfung des Tunnel-Dialogs (`tunnel-create.live.js`); T1–T3 ändern, was die Seiten „Verbindungen“ und Dashboard jeder Desktop-Journey zeigen. Kein `scenario` (kein FRP-Datenpfad, keine PKI, kein Install, keine Rust-Datei), kein `windows` (`fit_window_size`/`hdpi_scale` wirken nur unter Unix, `rdp_logic.rs:127`, `:143`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: —. Zeilenangaben gelten für `origin/main@b1432223` und werden beim Baustart neu gegreppt. Kein Risikopfad
nach `scripts/dev/review-risk.txt` (kein `security`-Prüfer). Alle Tasks nur unter `apps/desktop/ui/` (dazu
`CHANGELOG.md`, T10 `docs/admin/frp-tunnel.html` DE+EN); keine Datei unter `apps/desktop/src-tauri/`.

Ziel: (1) Ein gescheiterter Abruf lässt die Liste derselben Quelle stehen, und „Verbindungen“ und Dashboard zeigen
Fehler und Laden. (2) Der RDP-Start gibt Bildschirmgröße und Skalierungsfaktor mit. (3) Eine Regel für die Sprache
ohne gespeicherten Wert: die Systemsprache. (4) Löschen im Verbindungs-Editor fragt nach. (5) Speichern der
Einstellungen startet die Benachrichtigungen nicht neu. (6) Der Tunnel-Dialog prüft den Visitor-Port.

Für alle Tasks:
- Reihenfolge: T1 → T2 → T3 (T2 nutzt das Verhalten aus T1, T3 die Komponente aus T2); T5 → T6, T5 → T7; T4, T8,
  T9, T10 unabhängig. T2, T8 und T10 ändern `src/lib/i18n/dictionaries.ts`, fast alle Tasks `CHANGELOG.md`: ein
  Bauer, nacheinander.
- Neue i18n-Schlüssel in `de` und `en`; deren Verify nimmt `src/lib/i18n/i18n.test.ts` mit (Parität, keine unbenutzten
  Schlüssel). Neue Code-Strings (Kommentare, Testnamen) englisch.
- Neue Testdateien mit SPDX-Header wie `src/components/ConnectionEditor.lastused.test.ts:1-3`, neue `.svelte` wie
  `src/pages/Dashboard.svelte:1-5`.
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737.
- CHANGELOG unter `## [Unreleased]`, umlautfrei; T1–T3 ergänzen denselben Eintrag, T5–T7 ebenso.

### T1 — Verbindungsliste: ein gescheiterter Abruf behält die Liste derselben Quelle (R-0658)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connections.ts, apps/desktop/ui/src/lib/stores/connections.reload.test.ts, apps/desktop/ui/src/lib/stores/settings.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @50ab50b7 2026-10-22T10:29:27+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T1.verdict.json)
Änderung: `reloadForMode` (`connections.ts:105-127`) merkt sich bei Erfolg die Quelle der Liste in einer modul-lokalen `loadedFrom: string | null`: Server mit Sitzung → Art, `session.serverUrl` und `session.username`; Sync mit URL → Art und `settings.url`; sonst die Datei. Im `catch` (`:123-126`) bleiben `items`, wenn `loadedFrom` gleich der Quelle dieses Abrufs ist; sonst `items: []` und `loadedFrom = null`. `error` und `loading: false` wie bisher; der `loadGen`-Schutz (`:121`, `:124`) bleibt. `clearInMemory` (`:139-141`) und `load` (`:85-96`, Cache ohne Einstellungen) setzen `loadedFrom = null`. Den Kommentar in `settings.ts:56-58` („and empties the list“) an das neue Verhalten anpassen; Code dort unverändert. Neue Testdatei `connections.reload.test.ts` (Mocks wie `connections.server.test.ts:13-42`: `$lib/bridge` mit `fetchConnectionsJwt`, `syncConnections`, `loadConnections`; `reloadForMode` direkt mit Einstellungen und Sitzung rufen): (a) Server, erst `[A]`, dann lehnt `fetchConnectionsJwt` mit `offline` ab → `connections` ist `[A]`, `connectionsStore.error` `offline`, `loading` `false` (zuerst rot: `[]`); (b) dasselbe im Sync-Modus mit `syncConnections` (zuerst rot); (c) erst `[A]` für Benutzer `alice`, dann scheitert der Abruf für `bob` am selben Server → `[]`; (d) nach `clearInMemory` scheitert ein Abruf derselben Quelle → `[]`; (e) während ein Abruf hängt, bleibt `[A]` und `loading` ist `true`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connections.reload.test.ts src/lib/stores/settings.test.ts
Doku: CHANGELOG.md (Fixed: scheitert der Abruf der Verbindungen im Server- oder Sync-Modus, bleibt die zuletzt geladene Liste derselben Quelle stehen statt zu verschwinden)
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `connections.ts:123-126` setzt im Fehlerfall `items: []`; `settings.ts:56-58` beschreibt das („records the failure in the store's error state (and empties the list)“). Test (a) der Task ist auf HEAD rot (`[]` statt `[A]`)
Semantik: keine Stelle in docs/ — gesucht in `docs/developer/desktop.html` („Verbindungen laden“, `:258`), `docs/admin/*.html`; maßgeblich ist die Zeile („letzte Liste behalten, Fehler/Laden anzeigen“)
Dedup-Key: bug:desktop:connections.ts:fetch-error-clears-list
HEAD: b1432223

### T2 — „Verbindungen“ zeigt Laden und Ladefehler statt „Noch keine Verbindungen angelegt“ (R-0658)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionsLoadError.svelte, apps/desktop/ui/src/pages/Connections.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/pages/Connections.load.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @dd538e17 2026-10-22T10:41:12+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T2.verdict.json)
Änderung: Neue Komponente `ConnectionsLoadError.svelte` (SPDX): liest `connectionsStore` (`connections.ts:32`); ist `error` gesetzt, ein Banner mit `role="alert"` wie `MonitoringOverview.svelte:78-83` (Stil wie `.mon-error-banner`/`.mon-error-text`, `:247-261`): Text `connections.loadFailed` mit `{error}`, bei nicht leerer Liste dahinter `connections.loadFailed.kept`, Knopf `action.retry` → `loadForCurrentMode()`. `Connections.svelte` zeigt das Banner über der Liste; im Zweig der leeren Liste (`:246-249`) bei `$loading` `loading.generic`, bei gesetztem Fehler keinen weiteren Text, sonst `connections.empty` wie bisher. Neue Schlüssel: `connections.loadFailed` — „Die Verbindungen ließen sich nicht laden: {error}“ / „The connections did not load: {error}“ (Form wie `workspace.picker.listFailed`); `connections.loadFailed.kept` — „Angezeigt wird die zuletzt geladene Liste.“ / „The list shown is the one loaded last.“. Neue Testdatei `src/pages/Connections.load.test.ts`: die Seite mit dem echten Connections-Store rendern, `$lib/bridge` und `$lib/stores/session` gemockt (Server-Modus mit Sitzung, `fetchConnectionsJwt` steuerbar): (a) `fetchConnectionsJwt` lehnt mit `offline` ab → ein `role="alert"` mit dem Text von `connections.loadFailed` samt `offline`, kein `connections.empty` (zuerst rot); (b) solange der Abruf hängt → `loading.generic`, kein `connections.empty` (zuerst rot); (c) nach (a) „Erneut versuchen“, der zweite Abruf liefert `[A]` → die Karte von A steht da, das Banner ist weg; (d) erst `[A]`, dann scheitert ein Abruf → Banner mit `connections.loadFailed.kept`, A steht weiter da; (e) Erfolg mit `[]` → `connections.empty` wie bisher.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Connections.load.test.ts src/lib/i18n/i18n.test.ts
Doku: CHANGELOG.md (den Eintrag aus T1 ergänzen: „Verbindungen“ zeigt den Fehler mit „Erneut versuchen“ und waehrend des Ladens „Lade…“ statt „Noch keine Verbindungen angelegt“)
Abhängt von: T1
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `Connections.svelte:246-249` zeigt bei leerer Liste immer `connections.empty`; keine Komponente liest `error` oder `loading` des Stores (grep `connectionsStore`/`loading` über `src/**/*.svelte` ohne Treffer). Tests (a) und (b) sind auf HEAD rot
Dedup-Key: bug:desktop:connections.ts:fetch-error-clears-list
HEAD: b1432223

### T3 — Dashboard zeigt den Ladefehler und das Laden (R-0658)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Dashboard.svelte, apps/desktop/ui/src/pages/Dashboard.load.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @feeb8952 2026-10-22T10:49:41+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T3.verdict.json)
Änderung: `Dashboard.svelte` zeigt `ConnectionsLoadError` (aus T2) über `.dash-stats` (`:34`); das Feld „Zuletzt verwendet“ (`:56-77`) zeigt bei `$loading` und leerer Liste `loading.generic` statt `dashboard.empty`. Neue Testdatei `src/pages/Dashboard.load.test.ts`, Aufbau wie in T2: (a) `fetchConnectionsJwt` lehnt ab → `role="alert"` mit `connections.loadFailed` (zuerst rot); (b) solange der Abruf hängt → `loading.generic`, kein `dashboard.empty` (zuerst rot); (c) Erfolg mit `[]` → `dashboard.empty` wie bisher.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/pages/Dashboard.load.test.ts
Doku: CHANGELOG.md (den Eintrag aus T1/T2 ergänzen: auch das Dashboard zeigt den Fehler)
Abhängt von: T2
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `Dashboard.svelte:21` lädt beim Mount, `:75-77` zeigt bei leerer Liste `dashboard.empty`, kein Fehlertext. Tests (a) und (b) sind auf HEAD rot
Dedup-Key: bug:desktop:connections.ts:fetch-error-clears-list
HEAD: b1432223

### T4 — RDP-Start gibt Bildschirmgröße und Skalierungsfaktor mit (R-0659)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @ed58ab5d 2026-10-22T11:02:18+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T4.verdict.json)
Änderung: Neuer Helfer in `connectFlow.ts`, der beim Start (nicht beim Import: das Fenster kann den Bildschirm wechseln) `ClientInfo` (`src/lib/bridge/types.ts:91-95`) bildet: `screenWidth: window.screen.width`, `screenHeight: window.screen.height` (CSS-Pixel), `scaleFactor: window.devicePixelRatio || 1` — die Form des entfernten Plain-JS-Clients (`git show 4786c0a5^:desktop/src/platformApi.js`, Zeilen 185-191) und der Rust-Tests (`apps/desktop/src-tauri/src/connection/rdp_logic.rs:325`). `performConnect` gibt ihn bei RDP an `openConnectionStored` und `openConnection` statt `undefined` (`connectFlow.ts:269-271`); SSH und Web (`:276-279`) bleiben ohne `client`. Tests in `connectFlow.test.ts` (zuerst rot): Bildschirm 1920x1080 und `devicePixelRatio` 2 gestubbt (`window.screen` per `Object.defineProperty`/`vi.spyOn`, Rücknahme im `afterEach`) → (a) der Start mit Passwort-Dialog ruft `open_connection` und (b) der Start mit gespeichertem Passwort `open_connection_stored` je mit `client: { screenWidth: 1920, screenHeight: 1080, scaleFactor: 2 }` (im Aufbau mit frischem Modulgraph und `__TAURI_INTERNALS__`, wie `:200-258`). Die sechs Erwartungen `client: undefined` (`:257`, `:311`, `:393`, `:407`, `:420`, `:437`) pinnen den Fund: sie erwarten jetzt die `ClientInfo`, die ihr Test stubbt oder die jsdom liefert, als festen Wert (kein `expect.anything()`); keine Assertion entfällt. Rust bleibt unverändert.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: CHANGELOG.md (Fixed: unter Linux nimmt „Eingepasst“ die Groesse des Bildschirms statt immer 1088x720, „Automatisch“ erkennt HiDPI, „HiDPI“ waehlt den Faktor nach dem Bildschirm; auf einem HiDPI-Bildschirm nicht verifiziert)
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `connectFlow.ts:270-271` reicht `undefined` als `client`; `connectFlow.test.ts:257`, `:311`, `:393`, `:407`, `:420`, `:437` erwarten `client: undefined`; ohne `client` nimmt `fit_window_size` 1280x800 (`rdp_logic.rs:128-141`), `hdpi_scale` gibt `None` (`:144-160`). Tests (a) und (b) sind auf HEAD rot
Semantik: keine Stelle in docs/ (gesucht: HiDPI, Eingepasst, `/size`, `/scale`); die Optionen heißen „Eingepasst“, „Automatisch“, „HiDPI“ (`src/lib/i18n/dictionaries.ts:263-266`), Rust deutet `ClientInfo` in `rdp_logic.rs:128-160`
Dedup-Key: bug:desktop:connectFlow.ts:rdp-client-info-missing
HEAD: b1432223

### T5 — Sprache: ohne gespeicherten Wert gilt die Systemsprache (R-0660)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/index.ts, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @913eadb4 2026-10-22T11:23:18+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T5.verdict.json)
Änderung: Neu in `src/lib/i18n/index.ts`: `systemLanguage(): Language` (`navigator.language` beginnt mit `de` → `de`, sonst `en`, ohne `navigator` `en`; die Regel von `detectSystemLanguage`, `models/settings.ts:15-18`, die dorthin umzieht) und `resolveLanguage(stored: string | null | undefined): Language` (eine gültige gespeicherte Sprache, sonst `systemLanguage()`). `setLanguage` (`index.ts:38-45`) normalisiert mit `resolveLanguage` statt auf `en` (`:39`); damit gilt die Regel im Hydrate (`stores/session.ts:86`). `getSettingsDefaults` (`models/settings.ts:25`) nimmt `systemLanguage()`, `detectSystemLanguage` entfällt (einziger Nutzer). Der Anfangswert vor dem Laden (`index.ts:22`, `detectBrowserLanguage`) bleibt: T7. Tests in `i18n.test.ts` (`navigator.language` per `vi.spyOn(navigator, 'language', 'get')` gestubbt, Rücknahme im `afterEach`): `de-DE` → `setLanguage(null)` ergibt `de` (zuerst rot: `en`), `resolveLanguage(null)` `de`, `resolveLanguage('en')` `en`; `en-US` → `setLanguage(null)` `en`; `fr-FR` → `setLanguage(null)` `en`. `normalizes unknown language to en` (`:72-75`) bleibt grün (jsdom `en-US`).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n/i18n.test.ts src/lib/models/settings.test.ts
Doku: CHANGELOG.md (Fixed: ohne gespeicherte Sprache laeuft die Desktop-UI in der Systemsprache, Deutsch auf einem deutschen System, sonst Englisch)
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `index.ts:39` macht aus `null` `en`, `SettingsModal.svelte:92` macht aus `null` `de`, `index.ts:16-20` vor dem Laden die Browsersprache, sonst `de`; `apps/desktop/src-tauri/src/models.rs:131` gibt einer frischen Installation `language: None`. Der erste Test der Task ist auf HEAD rot
Semantik: keine Stelle in docs/ zur Rückfallsprache (gesucht: `docs/developer/desktop.html:124`, `:128` nennen die Sprache nur als globale Einstellung); maßgeblich ist die Zeile („null -> Systemsprache“)
Dedup-Key: bug:desktop:i18n/index.ts:three-language-fallbacks
HEAD: b1432223

### T6 — Einstellungen: das Sprach-Dropdown zeigt die Sprache, in der die UI läuft (R-0660)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.save.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a953bd35 2026-10-22T11:33:13+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T6.verdict.json)
Änderung: `SettingsModal.svelte:92` setzt `language = resolveLanguage(s.language)` statt `s.language === 'en' ? 'en' : 'de'`; der Typ von `language` (`:58`) wird `Language`. Gespeichert wird damit ohne Änderung des Dropdowns die aufgelöste Sprache (`onSave`, `:274-290`). Tests in `SettingsModal.save.test.ts` (gespeicherte Sprache `null` im Mock-Stand, `navigator.language` gestubbt): (a) `en-US` → das Dropdown (`languageSelect`, `:105-111`) steht auf `en`, und Speichern ohne Änderung schreibt `language: 'en'` (zuerst rot: `de`); (b) `de-DE` → `de`; der bestehende Test `keeps the remembered username when the language changes` bleibt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal.save.test.ts
Doku: CHANGELOG.md (den Eintrag aus T5 ergaenzen: der Einstellungsdialog zeigt diese Sprache, Speichern schaltet nicht mehr ungewollt auf Deutsch)
Abhängt von: T5
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `SettingsModal.svelte:92` zeigt bei `language: null` „Deutsch“, `:281` schreibt es beim Speichern jeder Einstellung mit. Test (a) ist auf HEAD rot
Dedup-Key: bug:desktop:i18n/index.ts:three-language-fallbacks
HEAD: b1432223

### T7 — Sprache vor dem Laden der Einstellungen nach derselben Regel (R-0660)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/index.ts, apps/desktop/ui/src/lib/i18n/i18n.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @22d052be 2026-10-22T11:43:30+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T7.verdict.json)
Änderung: Bei Antwort „Englisch“: der Anfangswert `writable(detectBrowserLanguage())` (`index.ts:22`) wird `writable(systemLanguage())`, `detectBrowserLanguage` (`:16-20`) entfällt (einziger Nutzer). Sichtbar nur bei einer anderen Systemsprache als Deutsch oder Englisch: „Lade…“ vor dem Laden (`App.svelte:22-25`) und die ganze UI, wenn das Laden der Einstellungen scheitert (`stores/session.ts:92-94`), werden englisch statt deutsch. Test in `i18n.test.ts`: `vi.resetModules()`, `navigator.language` `fr-FR`, frischer Import von `./index` → `get(language)` ist `en` (zuerst rot: `de`); `de-AT` → `de`. Bei Antwort „Deutsch wie heute“: `[~]` (zwei Regeln bleiben, die sich nur bei anderen Systemsprachen unterscheiden).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n/i18n.test.ts
Doku: CHANGELOG.md (den Eintrag aus T5 ergaenzen: auch vor dem Laden der Einstellungen)
Abhängt von: T5
Beweis: Code-Lesung origin/main@b1432223 — `index.ts:17-19` gibt für `fr-FR` `de`, nach dem Laden gilt `en` (`:39`, nach T5 `systemLanguage()`). Der Test der Task ist auf HEAD rot
Dedup-Key: bug:desktop:i18n/index.ts:three-language-fallbacks
HEAD: b1432223

### T8 — Verbindungs-Editor: Löschen erst nach Rückfrage (R-0661)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.delete.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0c711ddd 2026-10-22T11:58:54+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T8.verdict.json)
Änderung: `onDelete` (`ConnectionEditor.svelte:65-82`) fragt vor `remove` mit `confirmDialog($t('editor.deleteConfirm', { name }), { confirmLabel: $t('action.delete') })` wie `monitoring/AlertRuleModal.svelte:94-104` (`name`: Name, sonst Host der Verbindung); bei `false` geschieht nichts, der Editor bleibt offen. Die Verbindung wird vor der Frage festgehalten (wie `:67`). Das Overlay schließt auf Escape (`:111`), und der Fokus bleibt während der Frage auf „Löschen“ im Overlay: ein Zähler `asking` wie `SettingsModal.svelte:72-78`, `:182-186`, `:342` hält den Editor offen, solange die Frage steht. Neuer Schlüssel `editor.deleteConfirm` — „Verbindung „{name}“ wirklich löschen?“ / „Really delete the connection "{name}"?“. Neue Testdatei `ConnectionEditor.delete.test.ts` (Aufbau wie `ConnectionEditor.lastused.test.ts:20-26`, dazu `vi.mock('./ui/ConfirmDialog.svelte', …)` wie `SettingsModal.save.test.ts:90` und `$lib/bridge` mit `deletePassword`): (a) Antwort `false` → kein `remove`, kein `deletePassword`, der Editor ist offen (zuerst rot); (b) Antwort `true` bei einer RDP-Verbindung → `remove` mit ihrer `id`, `deletePassword`, der Editor zu; (c) die Frage nennt den Namen, `confirmLabel` ist `action.delete`; (d) Escape auf dem Overlay, solange die Frage offen ist (Promise noch nicht aufgelöst) → der Editor bleibt offen; danach `false` → nichts gelöscht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.delete.test.ts src/lib/i18n/i18n.test.ts
Doku: CHANGELOG.md (Fixed: „Loeschen“ im Verbindungs-Editor fragt nach, bevor es die Verbindung, im Server-Modus auf dem Server, und ein gespeichertes RDP-Passwort entfernt)
Beweis: Code-Audit 2026-10-21 · Code-Lesung origin/main@b1432223 — `ConnectionEditor.svelte:65-82` ruft `remove` ohne Rückfrage, `:240` bindet den Knopf direkt an `onDelete`. Test (a) ist auf HEAD rot
Semantik: keine Stelle in docs/; Muster der Desktop-UI: `confirmDialog` vor dem Löschen in `AlertRuleModal.svelte:94-104`, `MonitoringTemplateModal.svelte:175`, `Picker.svelte:118`
Dedup-Key: bug:desktop:ConnectionEditor.svelte:delete-without-confirm
HEAD: b1432223

### T9 — AppShell: Benachrichtigungen starten nur bei Wechsel von Server oder Benutzer neu (R-0663)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.notifications.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @5cca8d6a 2026-10-22T12:10:16+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T9.verdict.json)
Änderung: Der Effekt `AppShell.svelte:116-121` liest nicht mehr `$session`, sondern einen `$derived`-Schlüssel aus `serverUrl` und `username` der Sitzung (ein String, etwa per `JSON.stringify`, `null` ohne Sitzung): mit Schlüssel `activateNotifications()`, Cleanup `deactivateNotifications()`. `$derived` vergleicht mit `===`; ein neu gemeldetes Sitzungsobjekt mit gleichem Server und Benutzer (nach `refreshSettings`, `stores/session.ts:156-159`, meldet `derived` `:52` es neu) lässt den Effekt stehen. Ein Kommentar nennt das Warum. Neue Testdatei `AppShell.notifications.test.ts` (Aufbau wie `AppShell.workspace.test.ts:18-71`: `session`/`settings` als `writable`, Notifications-Store gemockt; Sitzungswechsel über den Store, nicht über `rerender`): (a) Sitzung A gesetzt → `activateNotifications` 1×; dann ein neues Objekt mit gleichem `serverUrl` und `username` gesetzt → weiter 1×, `deactivateNotifications` 0× (zuerst rot: 1× deactivate, 2× activate); (b) danach anderer `username` → deactivate 1×, activate 2×; (c) danach `null` → deactivate 2×, kein weiteres activate.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.notifications.test.ts src/components/AppShell.workspace.test.ts
Doku: CHANGELOG.md (Fixed: Speichern der Einstellungen startet die Benachrichtigungen nicht mehr neu; der Feed flackert nicht, und Meldungen aus dieser Luecke verlieren ihre OS-Benachrichtigung nicht)
Beweis: Code-Audit 2026-10-21 · Probe origin/main@b1432223 (Node v22.23.1, `svelte/store` aus `apps/desktop/ui/node_modules`, Svelte 5.56.2): `derived` über einen `writable` mit Sitzungsobjekt, ein Update, das nur `settings` ändert → der Abonnent wird zum zweiten Mal gerufen (Zähler 2 statt 1), dreimal identisch; `safe_not_equal` (`node_modules/svelte/src/internal/client/reactivity/equality.js:13-17`) hält Objekte nie für gleich, `store_get` reicht den Wert als `mutable_source` weiter (`.../reactivity/store.js:39`, `:64`). Test (a) ist auf HEAD rot
Dedup-Key: bug:desktop:AppShell.svelte:settings-save-restarts-stream
HEAD: b1432223

### T10 — Tunnel-Dialog prüft den Visitor-Port selbst (R-0585)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/frpTunnel.ts, apps/desktop/ui/src/lib/models/frpTunnel.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @7658ed40 2026-10-22T12:18:37+02:00
Review: approve (.ah-out/review/desktop-ui-fixes/T10.verdict.json)
Änderung: `validateTunnelForm` (`frpTunnel.ts:96-103`) lehnt bei `tunnelType === 'stcp'` einen `visitorPort`, der nicht `null` und keine ganze Zahl von 1 bis 65535 ist (`Number.isInteger`, wie `models/connection.ts:41-44`), mit `infra.tun.validation.visitorPortRange` ab. `null` (leeres Feld: der Server vergibt einen) bleibt erlaubt; bei HTTPS keine Prüfung (`formToInput` nullt den Port, `:89`). Neuer Schlüssel — „Visitor-Port muss zwischen 1 und 65535 liegen“ / „The visitor port must be between 1 and 65535“. Tests in `frpTunnel.test.ts` (zuerst rot): STCP mit 0, 65536, -1 und 1.5 → nicht ok mit dieser Meldung; 1, 65535 und `null` → ok; HTTPS mit 0 → ok. Der builder fährt zusätzlich `python3 scripts/dev/doc-smoke.py --paths --env --strict` (Exit 0, Ergebnis in den Commit-Body).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/frpTunnel.test.ts src/lib/i18n/i18n.test.ts
Doku: docs/admin/frp-tunnel.html:105 + docs/en/admin/frp-tunnel.html:105 (nach dem Satz zum 422: der Tunnel-Dialog des Desktop-Clients lehnt einen solchen Wert schon vor dem Speichern ab) · CHANGELOG.md (Changed: der Tunnel-Dialog des Desktops prueft den Visitor-Port 1-65535 vor dem Speichern)
Beweis: reviewer server-visitor-port, 2026-10-21 · Code-Lesung origin/main@b1432223 — `frpTunnel.ts:96-103` prüft `visitorPort` nicht; der Server nimmt nur 1–65535 (`apps/server/app/modules/frp/schemas.py:143-144`, `:248`, `:272`). Die Tests mit 0 und 65536 sind auf HEAD rot (`ok: true`)
Semantik: docs/admin/frp-tunnel.html:105 — „Ein angegebener Port liegt zwischen 1 und 65535; einen anderen Wert, auch <code>0</code>, lehnt der Server beim Anlegen und Ändern mit <code>422</code> ab.“ … „Abhilfe: im Tunnel-Dialog einen Port eintragen oder das Feld leeren, dann vergibt der Server einen freien.“
Dedup-Key: feat:desktop-ui:validateTunnelForm:visitor-port-range
HEAD: b1432223
