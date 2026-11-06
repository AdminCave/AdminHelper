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

### T1 — Desktop: Ringpuffer, Besitzer und Wiederanhängen einer Terminal-Sitzung (R-1070)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs
Änderung: `PtyRegistry` hält je Sitzung einen Ringpuffer (1 MiB) und das Label des Besitzer-Fensters; der Sink ist austauschbar. `attach(id, owner, sink)` schickt den Puffer, dann die laufende Ausgabe; ein Sink, der scheitert, wird abgehängt, ohne das Programm zu beenden (es puffert weiter). `close_all_of(owner)` ersetzt `close_all` für `terminal_close_all` (beim Exit bleibt `close_all`). Neuer Befehl `terminal_attach(id, output)`; `terminal_open_ssh` merkt sich das aufrufende Fenster. Tests: Puffer läuft über und behält das Ende, Wiederanhängen bekommt Puffer und dann Live-Ausgabe genau einmal, `close_all_of` lässt fremde Sitzungen laufen, Exit nach dem Abhängen kommt beim nächsten Sink an.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty
Doku: → T10
Test-Löschung: apps/desktop/src-tauri/src/pty.rs::a_sink_nobody_listens_to_ends_the_program — gewollte Verhaltensänderung (R-1070): ohne Zuhörer läuft das Programm weiter und puffert; Ersatz a_sink_nobody_listens_to_is_let_go_and_the_program_runs_on

### T2 — Desktop: abgedocktes Fenster und Rechte je Label (R-1070)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/src-tauri/capabilities/terminal-window.json, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs
Änderung: `terminal_detach(id, title)` (nur aus `main`) baut das Fenster `terminal-<id>` mit der UI-Route `#/detached/<id>`; `terminal_dock(id)` schließt es und meldet `terminal-docked {id}` an `main`; das Schließen über die Titelleiste meldet `terminal-window-closed {id}` an `main` (was daraus folgt, entscheidet T4). `build.rs` listet alle App-Befehle (`AppManifest::commands`); `default.json` (main) erlaubt alle, `terminal-window.json` nur `terminal_attach`, `terminal_write`, `terminal_resize`, `terminal_close`, `terminal_dock`, `load_settings` und die Ereignisse; die Terminal-Befehle lehnen aus einem `terminal-*`-Fenster jede andere Sitzung als `<id>` ab. Glob-Form der Fenster-Labels vor dem Bau im Schema von `tauri-utils` nachlesen. Test: die Liste in `build.rs` deckt `generate_handler!` und `default.json` genau (Quelltext-Test, CRLF normalisiert), Label-Prüfung je Befehl. `terminal-window.json` ohne SPDX-Kommentar (JSON), Lizenz über `REUSE.toml` prüfen. Risikopfad: `security`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- terminal
Doku: → T10
Abhängt von: T1

### T3 — Desktop: Ansible im Pseudo-Terminal und Probelauf (R-1073)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs
Änderung: Neuer Befehl `terminal_open_ansible(playbook_id, targets, check, cols, rows, output) -> u64` (nur Workspace-Seite, nur `main`): Playbook holen wie `ansible_run`, Dateien über `run`/`launch_ansible_with` (confined run dir) schreiben, `ansible-playbook -i <inv> [--check] <pb>` in `PtyRegistry` starten, das Run-Verzeichnis beim Ende der Sitzung löschen; scheitert der Start, wie heute löschen. `ansible_run` bekommt `check` und reicht `--check` in den OS-Terminal-Weg (`start_in_terminal`, `linux_run_script`). Tests: Argumente mit/ohne `--check` für beide Wege, Run-Verzeichnis nach dem Ende weg, nach gescheitertem Start weg.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible
Doku: → T10
Abhängt von: T1

### T4 — Desktop-UI: Abdocken und Andocken der Tabs [?] (Schließt das X der Titelleiste eines abgedockten Fensters die Sitzung oder dockt es an? Empfehlung: andocken) (R-1070)
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.sessions.test.ts
Änderung: `TerminalSession.detached`; `detachTerminal(key)` hängt das eigene Terminal ab und ruft `terminal_detach`; Tab mit Knopf *Abdocken*, Doppelklick und Ziehen nach unten (Schwelle wie im Mockup, 46 px); ein abgedockter Tab ist kursiv mit Symbol, ein Klick holt das Fenster nach vorn. Auf `terminal-docked` hängt der Store die Sitzung über `terminal_attach` wieder an (Puffer zuerst) und zeigt den Tab; auf `terminal-window-closed` nach Kevins Antwort. Tests je Weg und für Andocken mit Puffer.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- terminals AppShell
Doku: → T10
Abhängt von: T2

### T5 — Desktop-UI: das abgedockte Fenster (R-1070)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/main.ts, apps/desktop/ui/src/components/terminal/DetachedTerminal.svelte, apps/desktop/ui/src/components/terminal/DetachedTerminal.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/lib/bridge/index.ts
Änderung: Der Einstieg erkennt `#/detached/<id>` und rendert statt der App nur `DetachedTerminal`: Titel, Knopf *Andocken* (`terminal_dock`), das Terminal mit den Einstellungen des Nutzers, angehängt über `terminal_attach`; Eingaben und Größe gehen an die eigene Sitzung; kein `closeAllTerminals` in diesem Fenster. `SshTerminal` bekommt dafür eine Quelle statt des Store-Schlüssels (Store oder direkte Sitzung). Neue Dateien mit SPDX-Header. Tests: Anhängen, Eingabe, Andocken.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- DetachedTerminal SshTerminal
Doku: → T10
Abhängt von: T4

### T6 — Desktop: Einstellungen zum Wiederherstellen der Sitzungen [?] (Standardwert von „Letzte Sitzungen beim Start wiederherstellen“? Empfehlung: aus) (R-1070)
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/storage.rs
Änderung: `Settings.restore_sessions: bool` und `Settings.open_sessions: Vec<String>` (Verbindungs-IDs) mit `serde(default)`; Round-Trip-Test und Laden einer `prefs.json` ohne die Felder.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage models
Doku: → T10

### T7 — Desktop-UI: Wiederherstellen beim Start [?] (Standardwert wie T6) (R-1070)
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/components/settings/TerminalSection.svelte, apps/desktop/ui/src/components/settings/SettingsDialog.svelte, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/i18n/de.json, apps/desktop/ui/src/lib/i18n/en.json
Änderung: Schalter in den Terminal-Einstellungen; der Store schreibt die IDs der offenen SSH-Tabs in `openSessions`, sobald sich die Tabs ändern, und öffnet sie nach der Anmeldung neu (über `initiateConnect`, gleiche Reihenfolge, gelöschte Verbindungen übergangen), wenn `restoreSessions` an ist. Tests: an/aus, gelöschte Verbindung, Reihenfolge.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- terminals TerminalSection
Doku: → T10
Abhängt von: T6

### T8 — Desktop-UI: Ansible-Lauf im Tab und Probelauf-Schalter (R-1073)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/pages/Ansible.svelte, apps/desktop/ui/src/pages/Ansible.test.ts, apps/desktop/ui/src/lib/stores/ansible.ts, apps/desktop/ui/src/lib/stores/ansible.pipeline.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/i18n/de.json, apps/desktop/ui/src/lib/i18n/en.json
Änderung: Schalter „Probelauf (--check)“ auf der Ansible-Seite; bei `sshConsole = embedded` öffnet „Ausführen“ einen Tab vom Typ `ansible` (Titel = Playbook, `terminal_open_ansible`), sonst `ansible_run` wie bisher, beide mit `check`. Ein Ansible-Tab hat kein „Neu verbinden“ und wird nicht wiederhergestellt (T7). Tests: beide Wege, `check` durchgereicht, Tab-Titel.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- Ansible ansible terminals
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
