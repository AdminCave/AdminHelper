<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-terminal-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-terminal-2 · Review: pro Task
Spec: docs/features/kern-terminal-2.md (Roadmap R-1071, R-1072)
Heavy: linux-full + windows — linux-full: die Desktop-Journey `ssh-connect.live.js` bekommt Snippet und SFTP über den ControlMaster (`desktop_e2e_connect.sh` im Sammellauf); windows = die CI-Jobs `rust-windows` und `tauri-build-smoke` (der Pool hat keine Windows-Vorlage): Broadcast, der SFTP-Kanal ohne ControlMaster und die Dialoge sind auch Windows-Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Desktop: Snippets im workspace.json und in den Settings (R-1071)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/workspace.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/migration.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/validation.rs
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @a63b6c21 2026-11-06T14:50:13+01:00
Review: approve (.ah-out/review/kern-terminal-2/T1.verdict.json)
Änderung: `Snippet {name, command}` und `snippets: Option<Vec<Snippet>>` in `Settings` und `Meta` (`serde(default)`, camelCase), durchgereicht in `storage.rs` und in allen Konstruktoren. `save_settings` lehnt Listen über 200, Namen außerhalb 1–64 Zeichen oder mit Steuerzeichen und Befehle außerhalb 1–4096 Zeichen oder mit Steuerzeichen außer `\n`/`\t` ab. Tests: Rundweg `null`/`[]`/Liste durch `workspace.json`, alte Datei ohne Feld, jede Grenze; Wire-Form-Tests in `migration.rs`/`workspace.rs` nehmen das Feld auf; `types.ts` spiegelt es (Parität).
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T9

### T2 — Desktop: terminal_broadcast an alle laufenden SSH-Sitzungen (R-1071)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @e675fbbe 2026-11-06T15:06:08+01:00
Review: approve (.ah-out/review/kern-terminal-2/T2.verdict.json)
Änderung: `Spawn.broadcast` (ssh `true`, Ansible `false`), `PtyRegistry::broadcast(data) -> u32` schreibt an jede laufende Sitzung mit dem Flag, gleich welches Fenster sie besitzt. Befehl `terminal_broadcast` nur in `default.json` (nicht in `terminal-window.json`), registriert in `main.rs`/`build.rs`, Bridge `terminalBroadcast`. Tests: zwei ssh-artige und eine Ansible-artige Sitzung, eine beendete: nur die laufenden mit Flag bekommen die Bytes, die Zahl stimmt; Capability-Test (aus `terminal-*` abgelehnt), IPC-Inventar.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T9

### T3 — Desktop-UI: Snippet-Panel, Ausführen und Broadcast (R-1071)  [x]
Komponente: desktop · Dateien: apps/desktop/ui/src/components/terminal/SnippetsPanel.svelte, apps/desktop/ui/src/components/terminal/SnippetsPanel.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/session.ts, apps/desktop/ui/src/lib/stores/session.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts, apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/src/capabilities.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/src-tauri/capabilities/terminal-window.json, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @086f51ac 2026-11-06T15:41:46+01:00
Review: approve (.ah-out/review/kern-terminal-2/T3.verdict.json)
Änderung: Kopfknopf „Snippets“ (nicht im abgedockten Fenster), Panel schließt das der Optionen aus. Neue Komponente (SPDX): Karten aus `settings.snippets` bzw. der übersetzten Standardliste bei `null`; Klick schreibt den Befehl (Zeilen mit `\r`) plus `\r` über `writeTerminal`, mit Broadcast über `terminalBroadcast`; Neu/Bearbeiten/Löschen (Rückfrage) speichert die ganze Liste über `save_settings`; Checkbox „An alle SSH-Sitzungen senden“ als nicht gespeicherter Store in `terminals.ts`; Fußzeile „● Broadcast aktiv“ in jeder Sitzung, solange an. Karten deaktiviert, wenn die Sitzung nicht läuft. i18n DE/EN.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T9
Abhängt von: T1, T2

### T4 — Desktop: ControlMaster der Terminal-Sitzung und Argumente des SFTP-Kanals (R-1072)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/pty.rs
Änderung: Unter Unix startet `ssh_spawn` `ssh` mit `-o ControlMaster=yes -o ControlPath=<dir>/c -o ControlPersist=no`; `<dir>` ist ein 0700-Verzeichnis mit kurzem Namen (`create_run_dir` mitbenutzt, Socket-Pfad unter 100 Bytes, sonst Basis `/tmp`), entfernt über `Spawn.cleanup`; die Sitzung merkt sich den ControlPath. Neu `build_sftp_args(connection, control_path: Option<&Path>)`: `-p`, `-i`, `-J`, `-o` ohne `-L/-R/-D` und ohne `ForwardAgent`, dazu `-o BatchMode=yes`, mit Pfad `-o ControlMaster=no -o ControlPath=<p>`, dann `-s -- <ziel> sftp`. Tests der Argumentlisten (mit und ohne Pfad, mit Weiterleitungen, Windows ohne ControlMaster), Pfadlänge und Rechte des Verzeichnisses, Aufräumen nach dem Ende.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T9

### T5 — Desktop: SFTP-Kanal mit russh-sftp (R-1072)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, THIRD_PARTY_LICENSES.md
Änderung: Neues Modul (SPDX): `ssh` mit den Argumenten aus T4 über `tokio::process` starten (tokio-Features `process`, `io-util`), stdin/stdout als Stream an `SftpSession::new`; Operationen `list` (aufgelöster Pfad, Ordner zuerst, `..`), `mkdir`, `upload(local, remote_dir, overwrite, progress)` (vorhandene Datei ohne `overwrite`: eigener Fehler `exists`), `download(remote, local, progress)` mit Fortschritt in Schritten; der Prozess endet nach jeder Aktion, stderr von `ssh` wird zur Fehlermeldung (gekürzt, ohne Datei-Inhalt). Tests unter Linux gegen das echte `sftp-server` (`/usr/lib/openssh/sftp-server`, fehlt es: Test rot) als Programm statt `ssh`: Liste, Ordner anlegen, Hoch- und Herunterladen mit Prüfsumme, Überschreib-Schutz, Fortschritt. `russh-sftp` in `THIRD_PARTY_LICENSES.md`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp
Doku: → T9
Abhängt von: T4

### T6 — Desktop: SFTP-Befehle, Dialoge und gezogene Dateien (R-1072)  [ ]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/sftp.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts
Änderung: Befehle `sftp_list`, `sftp_mkdir`, `sftp_upload` (Datei-Dialog in Rust, `spawn_blocking`), `sftp_upload_dropped`, `sftp_download` (Speichern-Dialog in Rust) mit Fortschritt über `Channel`, nur `main`; Verbindung und ControlPath aus der Sitzung `session`, unbekannte oder beendete Sitzung → Fehler. `WindowEvent::DragDrop(Drop)` merkt die Pfade je Fenster unter einer fortlaufenden Nummer und meldet `sftp-drop {drop, names}`; `sftp_upload_dropped` nimmt nur die letzte Nummer dieses Fensters, Ordner abgelehnt. Bridge und Typen. Tests: Sitzung → Argumente, fremde/alte Drop-Nummer, Ordner im Drop, Capability (aus `terminal-*` abgelehnt), IPC-Inventar.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T9
Abhängt von: T5

### T7 — Desktop-UI: SFTP-Panel mit Drag & Drop (R-1072)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/FilesPanel.svelte, apps/desktop/ui/src/components/terminal/FilesPanel.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Kopfknopf „Dateien (SFTP)“ (nicht im abgedockten Fenster), drei Panels schließen sich aus. Neue Komponente (SPDX): Pfad-Pill, Liste (Ordner/Datei-Symbol, Name, Größe), Ordner öffnen, `..`, Datei-Klick lädt herunter, Hochladen, Neuer Ordner (Name abfragen), Aktualisieren, Drop-Zone über `sftp-drop`, Rückfrage bei `exists` und erneuter Aufruf mit Überschreiben, Fortschritt, Fehlermeldung; unter Windows nach gescheiterter Anmeldung der Hinweis auf Schlüssel/Agent. i18n DE/EN.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- FilesPanel SshTerminal i18n
Doku: → T9
Abhängt von: T3, T6

### T8 — Desktop-E2E: Snippet und SFTP in der SSH-Sitzung (R-1071, R-1072)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/ssh-connect.live.js
Änderung: Nach dem Verbinden im eingebetteten Terminal (Passwort-Anmeldung): ein Snippet anlegen und ausführen, seine Ausgabe im Terminal sehen; das SFTP-Panel öffnen (läuft über den ControlMaster, also ohne zweite Anmeldung), einen Ordner anlegen und nach Aktualisieren in der Liste sehen, hineinwechseln. Läuft im Sammellauf (`desktop_e2e_connect.sh`), lokal nur Lint.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T9
Abhängt von: T7

### T9 — Doku und CHANGELOG (R-1071, R-1072)  [ ]
Komponente: desktop-rs · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-terminal-2.md
Änderung: Nutzer-Doku DE+EN (SSH-Terminal: Snippets, Standardliste, Broadcast mit Warnung, Dateien-Panel, Windows-Hinweis); Entwickler-Doku DE+EN (IPC-Tabelle: `terminal_broadcast`, `sftp_*`; Abschnitt Terminal: Broadcast-Flag, ControlMaster und Socket-Verzeichnis, SFTP-Kanal je Aktion, Pfade nur aus Rust; `Settings`: `snippets` je Workspace). Changelog-Fragment (ohne Umlaute) unter `### Added`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp
Doku: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-terminal-2.md
Task-Review: am Ende

## Entscheidungen
- Kevin 2026-11-06: Snippets lokal je Workspace (`workspace.json`); Klick führt aus (Befehl + Enter); Broadcast nur für Snippets an alle verbundenen SSH-Sitzungen aller Fenster, Fußzeile „Broadcast aktiv“; SFTP über `ssh -s sftp` (System-OpenSSH) mit russh-sftp, Linux/macOS über den ControlMaster der Terminal-Sitzung, Windows zweite Anmeldung nur mit Schlüssel/Agent, sonst Hinweis im Panel.
- `snippets: null` heißt übersetzte Standardliste, `[]` heißt leer; die erste Änderung speichert die ganze Liste.
- Broadcast-Checkbox wird nicht gespeichert und ist beim Start aus.
- Ein SFTP-Kanal je Aktion, damit kein offener Kanal den Master nach `exit` der Shell hält.
- Lokale Pfade nur aus Rust (Dialoge, Drag-and-Drop-Ereignis), nie aus der Webview.
- Kein Löschen, Umbenennen oder rekursiver Ordner-Transfer im SFTP-Panel (Mockup zeigt es nicht); Überschreiben nur nach Rückfrage.
- T3: Gespeichert wird über `setSnippets` in `session.ts` (Muster `setFavoriteConnections`): die ganze Liste über den aktuellen Settings-Stand; Löschen sucht das Snippet nach der Rückfrage in der dann aktuellen Liste.
- T3: Snippet-Karten nur bei Status `connected` aktiv (auch nicht während `connecting`, damit kein Befehl in einer Anmeldeabfrage landet); kein Snippets-Knopf in Ansible-Läufen und im abgedockten Fenster, Fußzeile „Broadcast aktiv“ in jeder SSH-Sitzung, auch im abgedockten Fenster, nicht bei Ansible-Läufen.
- T3: Der Broadcast-Schalter liegt in Rust (`PtyRegistry`, aus beim Start, `terminal_set_broadcast` nur aus `main`, Ereignis `terminal-broadcast` an alle Fenster, `terminal_broadcast_state` auch für `terminal-*`), damit abgedockte Fenster warnen (Prüfer T3); `terminal_broadcast` schreibt bei ausgeschaltetem Broadcast nichts. T3 wird damit Komponente `desktop` (UI und Rust, 19 Dateien: ein Ablauf, gemeinsam getestet). Bearbeiten sucht das Snippet beim Speichern in der aktuellen Liste; ist es weg, landet die Änderung am Ende.
- T3: Der Broadcast bleibt über ein Abmelden hinweg an (Prüfer-Nit T3): die Spec sagt „bis zum Ende der App“, und die Fußzeile jeder SSH-Sitzung zeigt ihn.
- T3: Broadcast erreicht auch SSH-Sitzungen, die noch an Passwort- oder Hostkey-Abfrage stehen (Rust kennt den Unterschied nicht); das sagt die Doku (T9).
- T3: Namen und Befehle nur als Text gerendert; Steuerzeichen-Grenzen prüft Rust (T1). Leere Zeilen am Ende eines Befehls fallen weg, damit kein doppeltes Enter entsteht.
- T5/T6 tragen `sftp.rs` beide: T5 baut den Kanal ohne Tauri (testbar gegen `sftp-server`), T6 die Befehle; so bleibt die neue Abhängigkeit einzeln zurücknehmbar.
