<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Workspaces, Teil Oberfläche — Task-Ledger
Status: aktiv · Branch: feature/desktop-workspaces-ui · Review: pro Task
Spec: docs/features/desktop-workspaces.md (Roadmap R-0431, R-0524)
Heavy: none — Teil-Ledger von `tasks/desktop-workspaces.md`; die schweren Läufe fährt das Vorhaben dort
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-20: R-0431 baut in drei Spuren mit je eigenem Teil-Ledger, Branch und Worktree, damit die disjunkten Blöcke parallel laufen: Windows-RDP und Doku in `tasks/desktop-workspaces.md` (`feature/desktop-workspaces`), Oberfläche in `tasks/desktop-workspaces-ui.md` (`feature/desktop-workspaces-ui`), Live-E2E in `tasks/desktop-workspaces-e2e.md` (`feature/desktop-workspaces-e2e`). Die Teil-Branches werden in `feature/desktop-workspaces` gemergt, nie direkt in `main`; je Ledger höchstens ein Bauer.

## Block D — Oberfläche

### T18 — Workspace-Store, Modell und Start der Oberfläche  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/workspace.ts, apps/desktop/ui/src/lib/stores/workspace.test.ts, apps/desktop/ui/src/lib/models/workspace.ts, apps/desktop/ui/src/lib/models/workspace.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/stores/session.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @cfb61271 2026-10-20T13:10:40+02:00
Review: approve (.ah-out/review/desktop-workspaces-ui/T18.verdict.json)
Änderung: Neuer Store `stores/workspace.ts` (SPDX-Header): `context` aus `workspaceContext()`, `list`, Aktionen `refresh`, `save`, `remove`, `open`, `openLauncher`. Neues Modell `models/workspace.ts` (SPDX-Header): Palette (gleich der Rust-Konstante), `validateDraft` (Name; URL je Art mit den Regeln aus `validateSettings`), `hostOf(url)` für die Namensvorbelegung. `hydrate` (`session.ts:70`) lädt den Kontext mit; `needsLogin` gilt nur im Workspace-Prozess. Tests (beide neuen Testdateien mit SPDX-Header): Store mit gemockter Bridge; `validateDraft` und `hostOf`; `hydrate` im Launcher → kein Login, Server-Workspace ohne Sitzung → Login.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/workspace.test.ts src/lib/models/workspace.test.ts src/lib/stores/session.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T14

### T42 — `WorkspaceInfo` trägt die URL des Workspace  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @502e6880 2026-10-20T13:47:18+02:00
Review: approve (.ah-out/review/desktop-workspaces-ui/T42.verdict.json)
Änderung: Entscheidung Kevin 2026-10-20 (Frage des Bauers zu T19): `WorkspaceInfo` (`models.rs`) bekommt `url: Option<String>`, gefüllt in `Meta::info` (`workspace.rs`) aus der gespeicherten Workspace-URL ohne Benutzerteil (userinfo entfernt, sonst unverändert); ein Workspace ohne URL liefert `null`. `types.ts` zieht das Feld nach (camelCase wie die übrigen Felder). Der Vertrag von `save_workspace` bleibt: eine fehlende oder leere URL entfernt sie beim Bearbeiten. Tests: Rust-Test von `info` mit URL, ohne URL und mit userinfo (wird entfernt); ein bestehender Paritätstest zwischen Rust-Modell und `types.ts` (falls vorhanden) bleibt grün.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- workspace
Doku: keine (intern; Doku mit T33)
Abhängt von: T14

### T43 — URL im Launcher maskiert, beim Speichern unverändert behalten  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @8a13aee9 2026-10-20T14:06:50+02:00
Review: approve (.ah-out/review/desktop-workspaces-ui/T43.verdict.json)
Änderung: Entscheidung Kevin 2026-10-20 (Reviews T42): (1) `shown_url` (`workspace.rs`, T42) maskiert zusätzlich die Werte der Query (`?token=***`, Schlüssel bleiben sichtbar) und ein Fragment (`#***`); Benutzerteil weiter entfernt; nicht parsbar → `null`. (2) `launcher::edit` behält die gespeicherte URL samt Benutzerteil, Query und Fragment, wenn die gesendete URL gleich `shown_url(gespeicherte)` ist (auch wenn beide `null` sind, eine gespeicherte, aber nicht parsbare URL geht beim Bearbeiten also nicht verloren); eine wirklich geänderte URL ersetzt sie wie bisher, eine leere entfernt sie nur, wenn `shown_url` der gespeicherten nicht `null` ist. (3) Die Doc-Kommentare an `WorkspaceInfo.url` (`models.rs`, `types.ts`, `shown_url`) nennen Parser-Schreibweise, Maskierung und `null` bei nicht parsbarer URL (Nits T42). Tests (Namen enthalten `workspace_url`): Maskierung je Fall (Query mit mehreren Werten, Fragment, Benutzerteil plus Query); Bearbeiten mit unveränderter maskierter URL behält Benutzerteil und Token; geänderte URL ersetzt; leere URL entfernt; nicht parsbare gespeicherte URL bleibt beim Umbenennen erhalten; Identitäts-Prüfung bei Origin-Wechsel unverändert.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- workspace_url
Doku: keine (intern; Doku mit T33)
Abhängt von: T42

### T19 — Workspace-Editor: anlegen und bearbeiten  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/WorkspaceEditor.svelte, apps/desktop/ui/src/components/WorkspaceEditor.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/models/workspace.ts, apps/desktop/ui/src/lib/models/workspace.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @f19aa867 2026-10-20T16:03:27+02:00
Review: approve (.ah-out/review/desktop-workspaces-ui/T19.verdict.json)
Änderung: Neue Komponente (SPDX-Header): Art (Server/Sync/Lokal; beim Bearbeiten fest), Name (bei Server und Sync mit dem Host vorbelegt, bis der Nutzer ihn selbst ändert), Farbe aus der Palette, URL je Art; beim Ändern einer URL die Warnung, dass Anmeldung und Geräte-Identität zur alten Installation gehören und eine andere Installation ein neuer Workspace ist. Kein Netzkontakt. Texte DE+EN. Tests (SPDX-Header): Name folgt dem Host bis zur eigenen Eingabe; ungültige URL sperrt Speichern; URL-Änderung zeigt die Warnung; Speichern ruft `save` mit dem Entwurf. Nachtrag (T18-Bauer und -Review): Wechselt die Art auf Lokal, verwirft der Editor eine getippte URL (Rust lehnt einen lokalen Workspace mit URL ab); der aus dem Host vorbelegte Name wird auf `WORKSPACE_NAME_MAX` (40) gekürzt bzw. das Feld trägt `maxlength`, damit ein langer Host das Speichern nicht sperrt; ein migrierter Server-Workspace ohne URL lässt sich umbenennen, ohne eine URL eintragen zu müssen (die URL-Pflicht aus `validateDraft` gilt beim Anlegen und wenn eine URL schon besteht), Test dazu. Entscheidung Kevin 2026-10-20 (Frage des Bauers zu T19): Der Editor arbeitet auf einem `WorkspaceDraft` aus `WorkspaceInfo`, das seit T42 die URL trägt; beim Bearbeiten schickt er die URL unverändert mit, wenn sie nicht geändert wurde, und die Warnung bei einer URL-Änderung vergleicht alte und neue URL. Nachtrag (Kevin 2026-10-20, T43): `WorkspaceInfo.url` ist ohne Benutzerteil und mit maskierter Query; der Editor schickt sie beim Bearbeiten unverändert zurück, wenn der Nutzer das URL-Feld nicht ändert, und T43 behält dann die gespeicherte URL. Abhängt von T43. Nachtrag (T43-Reviews): Ändert der Nutzer die URL, die maskierte Werte (`***`) enthält, weist der Editor darauf hin, dass diese Werte neu einzutragen sind (eine geänderte URL ersetzt die gespeicherte wörtlich, `***` eingeschlossen); Test dazu.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/WorkspaceEditor.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

### T20 — Picker im Launcher  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Picker.svelte, apps/desktop/ui/src/components/Picker.test.ts, apps/desktop/ui/src/App.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Neue Komponente (SPDX-Header): Liste mit Farbpunkt, Name, Art-Icon, Host bzw. „Lokal“ und „geöffnet“; Vorauswahl `lastUsed`, Pfeiltasten und Enter öffnen; ein geöffneter Workspace lässt sich nicht öffnen (Hinweis); einmaliger Hinweis nach der Migration; „Neuer Workspace“ und „Bearbeiten“ (nur geschlossen) öffnen den Editor (T19); „Löschen“ nur geschlossen, die Bestätigung nennt den Namen, bei Lokal mit Datenverlust-Hinweis, nach `localOnly` der bekannte Hinweis „nur auf diesem Gerät“. `App.svelte` (`:20-28`) zeigt im Launcher den Picker. Texte DE+EN. Tests (SPDX-Header): Vorauswahl und Enter rufen `open(lastUsed)`; geöffneter → kein Aufruf; Löschen fragt mit Namen, `localOnly` → Hinweis; Migrationshinweis genau einmal. Nachtrag (T12): Der Picker sperrt den Öffnen-Knopf, solange `open_workspace` läuft (zwei gleichzeitige Aufrufe derselben Id liefern sonst beide Ok, das zweite Kind endet mit Exit 3). Nachtrag (T18-Bauer und -Review): `migratedNotice` liefert Rust nur beim ersten Listing; der Picker hält den Hinweis lokal fest, auch nach `refresh` durch `save`/`remove`. Der Picker sperrt den Öffnen-Knopf während `open`. Scheitert nach einem erfolgreichen `remove` nur das Neuladen der Liste, darf das `ResetOutcome` (etwa „nur auf diesem Gerät“) nicht verloren gehen: `remove` im Store gibt das Ergebnis zurück und meldet den Listenfehler getrennt (Store-Datei per `set-files`), Test dazu. Nachtrag (T19-Review): Wie bei `remove` darf auch `save` im Store nicht werfen, wenn `saveWorkspace` gelungen ist und nur das anschließende `refresh` scheitert (sonst legt ein zweiter Klick einen neuen Workspace doppelt an); der Listenfehler wird getrennt gemeldet, der Editor schließt; Test dazu.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Picker.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T19

### T21 — Workspace im Fenster kenntlich: Chip, Farbstreifen, „Workspaces…“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/ui/ConfirmDialog.svelte, apps/desktop/ui/src/styles/app.css, apps/desktop/ui/src/components/AppShell.workspace.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Ein Chip oben in der Sidebar (Farbpunkt + Name) ersetzt das Modus-Badge (`AppShell.svelte:101`, `:228`); Klick oder „Workspaces…“ ruft `openLauncher`. 4-px-Farbstreifen am Fensterrand in der Workspace-Farbe. Seiten mit `serverOnly` rendern nur bei `isServerMode` (`:87`), sonst das Dashboard (`currentId :91`). `ConfirmDialog` nennt im Workspace-Prozess Farbpunkt und Namen über der Frage. Texte DE+EN. Tests (neue Datei, SPDX-Header): Chip zeigt Name und Farbe, Klick ruft `openLauncher`; `/infrastructure` in einem lokalen Workspace zeigt das Dashboard; `ConfirmDialog` zeigt den Namen, im Launcher nicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.workspace.test.ts src/components/ui/primitives.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

### T22 — Login: „Anmelden bei ● Name“, feste URL, „Workspaces…“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/Login.workspace.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Überschrift „Anmelden bei ● <Name>“; die URL ist Anzeige, ein Eingabefeld gibt es im Login (`Login.svelte:264`) und in der Token-Registrierung (`:354`) nur, solange der Workspace keine URL hat. „Ohne Server fortfahren“ (`useLocal :138`, Knopf `:348`) wird „Workspaces…“ (`openLauncher`); `setMode` (`session.ts:152`) entfällt. Texte DE+EN. Die bestehenden `Login.*.test.ts` bleiben gültig (sie setzen keine URL). Tests (neue Datei, SPDX-Header): mit URL kein URL-Feld, Login nimmt die Workspace-URL; ohne URL das Feld wie heute; „Workspaces…“ ruft `openLauncher`. Nachtrag (T38-Reviews): `session.ts` (~:97) verschluckt Fehler beim Speichern nach dem Login (etwa `IDENTITY_WITHOUT_URL`); den Fehler anzeigen, mit dem Hinweis, die Geräte-Identität zurückzusetzen. Nach `URL_TAKEN` bei der Registrierung den Ausgang (`Revoked`/`LocalOnly`) nennen, sobald die UI ihn bekommt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

### T23 — Einstellungen: „Dieser Workspace“ und „Alle Workspaces auf diesem Gerät“  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.workspace.test.ts, apps/desktop/ui/src/lib/stores/settings.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/stores/session.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Das Modus-Radio (`SettingsModal.svelte:349-383`) entfällt. Abschnitt „Dieser Workspace“: Name, Farbe, URL als Anzeige mit dem Hinweis, dass sie im Picker bei geschlossenem Workspace änderbar sind, Abmelden, self-signed, Pin, Identität, Token, Browser-Zertifikat, Benachrichtigungsregeln, bei Sync das Intervall. Abschnitt „Alle Workspaces auf diesem Gerät“: Sprache, Passwörter, RDP, OS-Benachrichtigungen, Diagnose. `saveSettings` (`settings.ts:79-156`) ohne Moduswechsel und ohne erzwungenes Abmelden: prüfen, speichern, neu laden, Sprache setzen, bei Sync den Takt neu starten; Tunnel und Sitzung bleiben unberührt. `serverLogout` (`:158`) und `dropSession` (`session.ts:131`) verlieren ihre Aufrufer und gehen. Der Test `saving in server mode leaves a running tunnel alone (R-0245)` prüft künftig, dass Speichern weder Tunnel noch Abmelden anfasst. Brauchen bestehende `SettingsModal.*.test.ts` Mocks des Workspace-Stores, erweitert die Task `Dateien:` per `ledger.sh set-files`. Texte DE+EN. Tests (neue Datei, SPDX-Header): Abschnitte und Felder je Art; Speichern ruft weder `stopTunnel` noch `logout`; ein geändertes Sync-Intervall startet den Takt neu. Nachtrag (security T38): In Sync-Workspaces lehnt `reset_device_identity` jetzt ab; `SettingsModal.svelte` (`onResetDeviceIdentity`, `mode === 'sync'`) blendet die Aktion dort aus statt einen Fehler zu zeigen; Test dazu.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/settings.test.ts src/lib/stores/session.test.ts src/components/SettingsModal
Doku: keine (intern; Doku mit T33)
Abhängt von: T18
Test-Löschung: apps/desktop/ui/src/lib/stores/settings.test.ts::a server-URL change with an active session logs out before saving — im Workspace ist die URL fest, ein URL-Wechsel ist ein neuer Workspace; apps/desktop/ui/src/lib/stores/settings.test.ts::a server-URL change with an active session reloads the window after saving (R-0429) — wie oben; apps/desktop/ui/src/lib/stores/settings.test.ts::a server-URL change without a session saves without a reload — wie oben; apps/desktop/ui/src/lib/stores/settings.test.ts::a failed save after the forced logout does not reload — es gibt kein erzwungenes Abmelden mehr; apps/desktop/ui/src/lib/stores/settings.test.ts::saving in server mode still starts the tunnel when the status call fails — Speichern startet keinen Tunnel mehr, das tut der Start des Workspace-Fensters; apps/desktop/ui/src/lib/stores/settings.test.ts::saving in server mode starts the tunnel when none runs — wie oben; apps/desktop/ui/src/lib/stores/settings.test.ts::switching server->local stops the tunnel and drops the session — der Moduswechsel entfällt, die Art ist je Workspace fest; apps/desktop/ui/src/lib/stores/settings.test.ts::switching server->sync stops the tunnel and drops the session — wie oben; apps/desktop/ui/src/lib/stores/session.test.ts::ends the session in Rust and clears the in-memory one — `dropSession` hat keinen Aufrufer mehr; apps/desktop/ui/src/lib/stores/session.test.ts::still clears the local session when the server logout call fails — wie oben

### T24 — OS-Benachrichtigung mit Workspace-Präfix  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/osNotify.ts, apps/desktop/ui/src/lib/osNotify.test.ts
Änderung: `notifyOs` (`osNotify.ts:33-47`) stellt Einzel- und Sammelmeldung „[<Name>] “ voran, Name aus dem Workspace-Store; im Launcher ohne Präfix. Tests (neue Datei, SPDX-Header, Plugin gemockt): Präfix in beiden Wegen; ohne Workspace kein Präfix.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/osNotify.test.ts
Doku: keine (intern; Doku mit T33)
Abhängt von: T18

