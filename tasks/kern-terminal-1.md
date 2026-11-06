<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-terminal-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-terminal-1 · Review: pro Task
Spec: docs/features/kern-terminal-1.md (Roadmap R-1070, R-1073)
Heavy: linux-full + windows — linux-full: neue Desktop-Journey (Abdocken und Andocken in `ssh-connect.live.js`, `desktop_e2e_connect.sh` im Sammellauf); windows = die CI-Jobs `rust-windows` und `tauri-build-smoke` (der Pool hat keine Windows-Vorlage): ConPTY, Fensterrechte und der Ansible-Start sind auch Windows-Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@79878e61`. Mockup AdminCave/DesignSystem@244e890; Kevins Entscheidung vom 2026-11-02 in R-1070 (echtes Tauri-Fenster).

### T1 — Desktop: Ringpuffer, Besitzer und Wiederanhängen einer Terminal-Sitzung (R-1070)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @019ec51d 2026-11-06T09:47:44+01:00
Review: approve (.ah-out/review/kern-terminal-1/T1.verdict.json)
Änderung: `PtyRegistry` hält je Sitzung einen Ringpuffer (1 MiB) und das Label des Besitzer-Fensters; der Sink ist austauschbar. `attach(id, owner, sink)` schickt den Puffer, dann die laufende Ausgabe; ein Sink, der scheitert, wird abgehängt, ohne das Programm zu beenden (es puffert weiter). `close_all_of(owner)` ersetzt `close_all` für `terminal_close_all` (beim Exit bleibt `close_all`). Neuer Befehl `terminal_attach(id, output)`; `terminal_open_ssh` merkt sich das aufrufende Fenster. Tests: Puffer läuft über und behält das Ende, Wiederanhängen bekommt Puffer und dann Live-Ausgabe genau einmal, `close_all_of` lässt fremde Sitzungen laufen, Exit nach dem Abhängen kommt beim nächsten Sink an.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty
Doku: → T10
Test-Löschung: apps/desktop/src-tauri/src/pty.rs::a_sink_nobody_listens_to_ends_the_program — gewollte Verhaltensänderung (R-1070): ohne Zuhörer läuft das Programm weiter und puffert; Ersatz a_sink_nobody_listens_to_is_let_go_and_the_program_runs_on

### T2 — Desktop: abgedocktes Fenster und Rechte je Label (R-1070)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/src-tauri/capabilities/terminal-window.json, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/capabilities.rs, .gitignore
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5d78a2d4 2026-11-06T10:02:56+01:00
Review: approve (.ah-out/review/kern-terminal-1/T2.verdict.json)
Änderung: `terminal_detach(id, title)` (nur aus `main`) baut das Fenster `terminal-<id>` mit der UI-Route `#/detached/<id>`; `terminal_dock(id)` schließt es und meldet `terminal-docked {id}` an `main`; das Schließen über die Titelleiste meldet `terminal-window-closed {id}` an `main` (was daraus folgt, entscheidet T4). `build.rs` listet alle App-Befehle (`AppManifest::commands`); `default.json` (main) erlaubt alle, `terminal-window.json` nur `terminal_attach`, `terminal_write`, `terminal_resize`, `terminal_close`, `terminal_dock`, `load_settings` und die Ereignisse; die Terminal-Befehle lehnen aus einem `terminal-*`-Fenster jede andere Sitzung als `<id>` ab. Glob-Form der Fenster-Labels vor dem Bau im Schema von `tauri-utils` nachlesen. Test: die Liste in `build.rs` deckt `generate_handler!` und `default.json` genau (Quelltext-Test, CRLF normalisiert), Label-Prüfung je Befehl. Aus dem T1-Review: Logout (`logout`) schließt die abgedockten Fenster und alle Sitzungen (`close_all`); `WindowEvent::Destroyed` eines `terminal-<id>`-Fensters gibt dessen Sitzungen an `main` zurück (Besitzer `main`, ohne Sink, der Ringpuffer hält die Ausgabe), Test dazu. `terminal-window.json` ohne SPDX-Kommentar (JSON), Lizenz über `REUSE.toml` prüfen. Risikopfad: `security`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T10
Abhängt von: T1

### T3 — Desktop: Ansible im Pseudo-Terminal und Probelauf (R-1073)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @1edc6e5f 2026-11-06T10:14:48+01:00
Review: approve (.ah-out/review/kern-terminal-1/T3.verdict.json)
Änderung: Neuer Befehl `terminal_open_ansible(playbook_id, targets, check, cols, rows, output) -> u64` (nur Workspace-Seite, nur `main`): Playbook holen wie `ansible_run`, Dateien über `run`/`launch_ansible_with` (confined run dir) schreiben, `ansible-playbook -i <inv> [--check] <pb>` in `PtyRegistry` starten, das Run-Verzeichnis beim Ende der Sitzung löschen; scheitert der Start, wie heute löschen. `ansible_run` bekommt `check` und reicht `--check` in den OS-Terminal-Weg (`start_in_terminal`, `linux_run_script`). Tests: Argumente mit/ohne `--check` für beide Wege, Run-Verzeichnis nach dem Ende weg, nach gescheitertem Start weg.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T10
Abhängt von: T1

### T4 — Desktop-UI: Abdocken und Andocken der Tabs (R-1070)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.sessions.test.ts, apps/desktop/ui/src/components/terminal/SessionTabs.svelte, apps/desktop/ui/src/components/terminal/SessionTabs.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @2c150604 2026-11-06T11:10:02+01:00
Review: approve (.ah-out/review/kern-terminal-1/T4.verdict.json)
Änderung: `TerminalSession.detached`; `detachTerminal(key)` hängt das eigene Terminal ab und ruft `terminal_detach`; Tab mit Knopf *Abdocken*, Doppelklick und Ziehen nach unten (Schwelle wie im Mockup, 46 px); ein abgedockter Tab ist kursiv mit Symbol, ein Klick holt das Fenster nach vorn. Auf `terminal-docked` hängt der Store die Sitzung über `terminal_attach` wieder an (Puffer zuerst) und zeigt den Tab; auf `terminal-window-closed` nach Kevins Antwort. Tests je Weg und für Andocken mit Puffer.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- terminals AppShell SessionTabs
Doku: → T10
Abhängt von: T2

### T5 — Desktop-UI: das abgedockte Fenster (R-1070)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/main.ts, apps/desktop/ui/src/components/terminal/DetachedTerminal.svelte, apps/desktop/ui/src/components/terminal/DetachedTerminal.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @fc8d32aa 2026-11-06T11:28:36+01:00
Review: approve (.ah-out/review/kern-terminal-1/T5.verdict.json)
Änderung: Der Einstieg erkennt `#/detached/<id>` und rendert statt der App nur `DetachedTerminal`: Titel, Knopf *Andocken* (`terminal_dock`), das Terminal mit den Einstellungen des Nutzers, angehängt über `terminal_attach`; Eingaben und Größe gehen an die eigene Sitzung; kein `closeAllTerminals` in diesem Fenster. `SshTerminal` bekommt dafür eine Quelle statt des Store-Schlüssels (Store oder direkte Sitzung). Neue Dateien mit SPDX-Header. Tests: Anhängen, Eingabe, Andocken.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- DetachedTerminal SshTerminal terminals
Doku: → T10
Abhängt von: T4

### T6 — Desktop: Einstellungen zum Wiederherstellen der Sitzungen (R-1070)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/migration.rs, apps/desktop/ui/src/lib/bridge/types.ts
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @250aa0e0 2026-11-06T10:50:30+01:00
Review: approve (.ah-out/review/kern-terminal-1/T6.verdict.json)
Änderung: `Settings.restore_sessions: bool` und `Settings.open_sessions: Vec<String>` (Verbindungs-IDs) mit `serde(default)`; Round-Trip-Test und Laden einer `prefs.json` ohne die Felder.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage
Doku: → T10

### T7 — Desktop-UI: Wiederherstellen beim Start (R-1070)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/settings/TerminalSection.svelte, apps/desktop/ui/src/components/settings/SettingsDialog.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts, apps/desktop/ui/src/components/AppShell.shell.test.ts, apps/desktop/ui/src/components/AppShell.sessions.test.ts, apps/desktop/ui/src/components/AppShell.workspace.test.ts, apps/desktop/ui/src/components/AppShell.notifications.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @980913bf 2026-11-06T11:46:01+01:00
Review: approve (.ah-out/review/kern-terminal-1/T7.verdict.json)
Änderung: Schalter in den Terminal-Einstellungen; der Store schreibt die IDs der offenen SSH-Tabs in `openSessions`, sobald sich die Tabs ändern, und öffnet sie nach der Anmeldung neu (über `initiateConnect`, gleiche Reihenfolge, gelöschte Verbindungen übergangen), wenn `restoreSessions` an ist. Tests: an/aus, gelöschte Verbindung, Reihenfolge.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- terminals SettingsModal.save AppShell
Doku: → T10
Abhängt von: T6

### T8 — Desktop-UI: Ansible-Lauf im Tab und Probelauf-Schalter (R-1073)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Ansible.svelte, apps/desktop/ui/src/pages/Ansible.test.ts, apps/desktop/ui/src/lib/stores/ansible.ts, apps/desktop/ui/src/lib/stores/ansible.pipeline.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/components/AppShell.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @08160884 2026-11-06T12:00:39+01:00
Review: approve (.ah-out/review/kern-terminal-1/T8.verdict.json)
Änderung: Schalter „Probelauf (--check)“ auf der Ansible-Seite; bei `sshConsole = embedded` öffnet „Ausführen“ einen Tab vom Typ `ansible` (Titel = Playbook, `terminal_open_ansible`), sonst `ansible_run` wie bisher, beide mit `check`. Ein Ansible-Tab hat kein „Neu verbinden“ und wird nicht wiederhergestellt (T7). Tests: beide Wege, `check` durchgereicht, Tab-Titel.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- Ansible ansible terminals SshTerminal AppShell
Doku: → T10
Abhängt von: T3, T4

### T9 — Desktop-E2E: Abdocken und Andocken einer SSH-Sitzung (R-1070)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/ssh-connect.live.js
Änderung: Nach dem Verbinden im eingebetteten Terminal: Abdocken, in das zweite Fenster wechseln (`getWindowHandles`), dort einen Befehl tippen und seine Ausgabe sehen, Andocken, im Tab die Ausgabe von vorher und eine neue sehen. Läuft im Sammellauf (`desktop_e2e_connect.sh`), lokal nur Lint.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T10
Abhängt von: T5

### T10 — Doku und CHANGELOG (R-1070, R-1073)  [ ]
Komponente: desktop-rs · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, README.md, changelog.d/kern-terminal-1.md
Änderung: Abschnitt zum eingebetteten Terminal DE+EN: Abdocken und Andocken, Ringpuffer, Rechte des abgedockten Fensters, Wiederherstellen, Ansible im Tab mit Probelauf; neue Befehle. README: Einstellung „Sitzungen wiederherstellen“ im Abschnitt Terminal. Changelog-Fragment (ohne Umlaute) unter `### Added`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty
Doku: die genannten Dateien
Task-Review: am Ende

## Entscheidungen
- Ringpuffer 1 MiB je Sitzung im Backend (Spec, Trade-offs); ein Fenster je abgedockter Sitzung, Label `terminal-<id>`.
- Rechte doppelt: Capability je Label und Label-Prüfung in jedem Terminal-Befehl, weil die Glob-Form der Labels in der Tauri-Doku nicht belegt ist.
- Wiederherstellen öffnet die Verbindungen neu; eine laufende Sitzung überlebt keinen Neustart der App (Nicht-Ziel).
- T2: `Verify:` ohne Filter: die Tests liegen in `capabilities`, `commands` und `pty`, kein Name trifft alle. Die von tauri-build erzeugten `permissions/autogenerated/` sind gitignored (bei jedem Build neu). `terminal-window.json` ohne SPDX wie `default.json` (kein REUSE-Lint im Repo). Das abgedockte Fenster bekommt `terminal_close_all` nicht; ob es beim Neuladen etwas schließt, entscheidet T5.
- T1: Die Wiedergabe des Ringpuffers endet mit `{"replayed":true}`; die UI beantwortet Terminal-Abfragen davor nicht (T4/T5), sonst gingen alte Antworten erneut an das Programm. Eine Sitzung ohne Sink läuft weiter; nur ein zugestelltes Ende oder `terminal_close` entfernt sie.
- T3: `--check` steht hinter dem Playbook (`-i <inv> <pb> --check`, Ansible nimmt Optionen nach dem Argument), so bleiben die Dateien für beide Wege an ihrer Stelle. Die Sitzung löscht das Run-Verzeichnis über `Spawn::cleanup`, sobald das Programm endet; scheitert der Start, löscht es `launch_ansible_with` wie bisher. `ansible_run` nimmt `check` als `Option<bool>` (fehlt: echter Lauf), damit die UI bis T8 unverändert weiterläuft. `Verify:` ohne Filter: die Tests liegen in `ansible`, `pty` und `capabilities`.
- Kevin 2026-11-06: Das X der Titelleiste eines abgedockten Fensters dockt die Sitzung an (T4, T5); „Letzte Sitzungen beim Start wiederherstellen“ ist standardmäßig aus (T6, T7).
- T6: `openSessions` liegt in `workspace.json` (wie `favoriteConnections`), nicht in `prefs.json`: Verbindungs-IDs gehören zu einem Workspace, `prefs.json` gilt für das Gerät. `restoreSessions` liegt in `prefs.json`. Verify `-- storage` statt `-- storage models` (cargo test nimmt einen Filter).
- T5: Das abgedockte Fenster nutzt denselben Store mit einer übernommenen Sitzung (`adoptTerminal`) statt einer eigenen Quelle für `SshTerminal`: Replay, Status und Exit bleiben eine Logik. Es kennt nur die id, den Namen trägt die Titelleiste. Eine Sitzung, die beim Andocken kein Tab kennt (Hauptfenster neu geladen), wird beendet statt verwaist.
- T7: Das Wiederherstellen öffnet über `initiateConnect` mit Konsole `embedded` (gleicher Weg wie ein Klick, Host-Key-Prüfung inklusive), auch wenn `sshConsole` auf `external` steht: es stellt Tabs wieder her. Nacheinander in der gespeicherten Reihenfolge; eine gelöschte Verbindung oder eine ohne Tab nach dem Start fällt aus der Liste. Gespeichert wird erst, wenn die Verbindungen da sind, und der Logout (`closeAllTerminals`) beendet das Mitschreiben vorher, damit er die Liste nicht leert. Die Abhängigkeiten kommen per Injektion (`SessionKeeping`), weil `connectFlow.ts` den Store importiert. Zwölf Dateien: die vier AppShell-Tests brauchen `connectionsStore` und `setOpenSessions` im Mock; `types.ts` braucht nichts mehr (T6), die i18n-Texte liegen in `dictionaries.ts`, nicht in `de.json`/`en.json` (auch T8 korrigiert).
- T8: Ein Ansible-Tab ist eine Sitzung mit synthetischer Connection (leere id, Name = Playbook) und `ansible: {check}` statt eines eigenen Tab-Typs: Tabs, Abdocken und Ausgabe bleiben ein Weg; `reconnectTerminal` und `openSessionIds` lassen ihn aus. Eingebettet zeigt der Tab den Start, die Statusmeldung `ansibleStarted` bleibt dem OS-Terminal-Weg.
