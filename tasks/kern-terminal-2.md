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

### T4 — Desktop: ControlMaster der Terminal-Sitzung und Argumente des SFTP-Kanals (R-1072)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/pty.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @393d0d95 2026-11-06T15:55:55+01:00
Review: approve (.ah-out/review/kern-terminal-2/T4.verdict.json)
Änderung: Unter Unix startet `ssh_spawn` `ssh` mit `-o ControlMaster=yes -o ControlPath=<dir>/c -o ControlPersist=no`; `<dir>` ist ein 0700-Verzeichnis mit kurzem Namen (`create_run_dir` mitbenutzt, Socket-Pfad unter 100 Bytes, sonst Basis `/tmp`), entfernt über `Spawn.cleanup`; die Sitzung merkt sich den ControlPath. Neu `build_sftp_args(connection, control_path: Option<&Path>)`: `-p`, `-i`, `-J`, `-o` ohne `-L/-R/-D` und ohne `ForwardAgent`, dazu `-o BatchMode=yes`, mit Pfad `-o ControlMaster=no -o ControlPath=<p>`, dann `-s -- <ziel> sftp`. Tests der Argumentlisten (mit und ohne Pfad, mit Weiterleitungen, Windows ohne ControlMaster), Pfadlänge und Rechte des Verzeichnisses, Aufräumen nach dem Ende.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T9

### T5 — Desktop: SFTP-Kanal mit russh-sftp (R-1072)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, THIRD_PARTY_LICENSES.md, apps/desktop/src-tauri/src/error.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @dc00284e 2026-11-06T16:14:29+01:00
Review: approve (.ah-out/review/kern-terminal-2/T5.verdict.json)
Änderung: Neues Modul (SPDX): `ssh` mit den Argumenten aus T4 über `tokio::process` starten (tokio-Features `process`, `io-util`), stdin/stdout als Stream an `SftpSession::new`; Operationen `list` (aufgelöster Pfad, Ordner zuerst, `..`), `mkdir`, `upload(local, remote_dir, overwrite, progress)` (vorhandene Datei ohne `overwrite`: eigener Fehler `exists`), `download(remote, local, progress)` mit Fortschritt in Schritten; der Prozess endet nach jeder Aktion, stderr von `ssh` wird zur Fehlermeldung (gekürzt, ohne Datei-Inhalt). Tests unter Linux gegen das echte `sftp-server` (`/usr/lib/openssh/sftp-server`, fehlt es: Test rot) als Programm statt `ssh`: Liste, Ordner anlegen, Hoch- und Herunterladen mit Prüfsumme, Überschreib-Schutz, Fortschritt. `russh-sftp` in `THIRD_PARTY_LICENSES.md`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp
Doku: → T9
Abhängt von: T4

### T6 — Desktop: SFTP-Befehle, Dialoge und gezogene Dateien (R-1072)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/sftp.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/build.rs, apps/desktop/src-tauri/capabilities/default.json, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts, apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/ansible.rs, apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/ui/src/lib/bridge/types.parity.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop desktop-ui: 3 passed, 0 failed, 15 skipped @86b7c887 2026-11-06T16:48:05+01:00
Review: approve (.ah-out/review/kern-terminal-2/T6.verdict.json)
Änderung: Befehle `sftp_list`, `sftp_mkdir`, `sftp_upload` (Datei-Dialog in Rust, `spawn_blocking`), `sftp_upload_dropped`, `sftp_download` (Speichern-Dialog in Rust) mit Fortschritt über `Channel`, nur `main`; Verbindung und ControlPath aus der Sitzung `session`, unbekannte oder beendete Sitzung → Fehler. `WindowEvent::DragDrop(Drop)` merkt die Pfade je Fenster unter einer fortlaufenden Nummer und meldet `sftp-drop {drop, names}`; `sftp_upload_dropped` nimmt nur die letzte Nummer dieses Fensters, Ordner abgelehnt. Bridge und Typen. Tests: Sitzung → Argumente, fremde/alte Drop-Nummer, Ordner im Drop, Capability (aus `terminal-*` abgelehnt), IPC-Inventar.
Verify: bash scripts/dev/verify.sh desktop desktop-ui --strict
Doku: → T9
Abhängt von: T5

### T7 — Desktop-UI: SFTP-Panel mit Drag & Drop (R-1072)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/FilesPanel.svelte, apps/desktop/ui/src/components/terminal/FilesPanel.test.ts, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @a9471432 2026-11-06T17:13:05+01:00
Review: approve (.ah-out/review/kern-terminal-2/T7.verdict.json)
Änderung: Kopfknopf „Dateien (SFTP)“ (nicht im abgedockten Fenster), drei Panels schließen sich aus. Neue Komponente (SPDX): Pfad-Pill, Liste (Ordner/Datei-Symbol, Name, Größe), Ordner öffnen, `..`, Datei-Klick lädt herunter, Hochladen, Neuer Ordner (Name abfragen), Aktualisieren, Drop-Zone über `sftp-drop`, Rückfrage bei den Namen in `existing` und erneuter Aufruf von `sftp_upload_dropped` mit derselben Nummer und `overwrite`, Fortschritt, Fehlermeldung; unter Windows nach gescheiterter Anmeldung der Hinweis auf Schlüssel/Agent. i18n DE/EN.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- FilesPanel SshTerminal i18n
Doku: → T9
Abhängt von: T3, T6

### T8 — Desktop-E2E: Snippet und SFTP in der SSH-Sitzung (R-1071, R-1072)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/ssh-connect.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @eb5e0cac 2026-11-06T17:18:42+01:00
Review: approve (.ah-out/review/kern-terminal-2/T8.verdict.json)
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
- T4: Der Socket-Pfad bleibt höchstens 80 Byte lang statt „unter 100“: ssh bindet erst `<ControlPath>.<16 Zeichen>` (OpenSSH mux.c, `muxserver_listen`), `sun_path` hat unter macOS 104 Byte. Ein Temp-Verzeichnis mit Zeichen außer `A-Za-z0-9/._-` weicht ebenfalls auf `/tmp` aus (ssh trennt `-o`-Werte an Leerzeichen und expandiert `%`). Das Verzeichnis entsteht erst in `terminal_open_ssh` nach der Port-Prüfung (`with_control_master`, `control_dir`); scheitert der Start, löscht der Befehl es. `ansible::create_run_dir` wird zu `create_private_dir(base, prefix)` verallgemeinert.
- T4: Der SFTP-Kanal setzt wie sftp(1) `ClearAllForwardings=yes`, `ForwardAgent=no`, `ForwardX11=no`, `PermitLocalCommand=no` (Prüfer Runde 1): auch Weiterleitungen aus `~/.ssh/config` binden nicht erneut. Nit offen gelassen: scheitert das ControlMaster-Verzeichnis (Temp und `/tmp` nicht beschreibbar), startet das Terminal nicht; ohne beschreibbares Temp scheitern auch Ansible-Läufe, ein stiller Start ohne Master ließe SFTP später rätselhaft scheitern.
- T3: Broadcast erreicht auch SSH-Sitzungen, die noch an Passwort- oder Hostkey-Abfrage stehen (Rust kennt den Unterschied nicht); das sagt die Doku (T9).
- T3: Namen und Befehle nur als Text gerendert; Steuerzeichen-Grenzen prüft Rust (T1). Leere Zeilen am Ende eines Befehls fallen weg, damit kein doppeltes Enter entsteht.
- T5/T6 tragen `sftp.rs` beide: T5 baut den Kanal ohne Tauri (testbar gegen `sftp-server`), T6 die Befehle; so bleibt die neue Abhängigkeit einzeln zurücknehmbar.
- T5: Kanal über `russh-sftp` 3.0.1 an stdin/stdout des ssh-Kinds (tokio-Feature `fs` zusätzlich). Ein vorhandenes Ziel ohne Überschreiben ist `AppError::SftpExists` (`ERR_SFTP_EXISTS`); Upload mit `EXCLUDE` bzw. `TRUNCATE`, ein Ordner als Quelle wird vor dem Öffnen auf dem Server abgelehnt (Prüfer-Nit T5). Download schreibt `.<name>.ah-part` neben dem Ziel, dann `sync_all` und `rename`, bei Fehler fällt die Teildatei weg. Fehlermeldung: die letzte nicht leere stderr-Zeile (höchstens 512 Zeichen), nur wenn das Kind schon geendet hat. Die Tests gegen `/usr/lib/openssh/sftp-server` laufen nur unter Linux (Prüfer Runde 1: der Windows-Runner hat keinen); fehlt der Server, sind sie rot, kein SKIP.
- T6: Abweichung vom IPC-Vertrag der Spec: `sftp_upload` liefert `{drop, uploaded, existing}` oder `null` (Abbruch) statt `u32`, `sftp_upload_dropped` hat zusätzlich `overwrite` und liefert dasselbe. Grund: der Upload bricht bei einer vorhandenen Datei nicht ab, sondern nennt sie in `existing`; die UI fragt einmal und ruft mit derselben Nummer und `overwrite` erneut auf, Hochgeladenes hat den Drop schon verlassen. Dialog-Auswahl und Drop teilen sich die Nummern von `main`: ein neuer Drop verdrängt eine Auswahl, deren Rückfrage noch offen ist (die UI meldet dann den Fehler der veralteten Nummer).
- T6: Ordner lehnen den ganzen Drop vorab ab. Die serde-Typen heißen `Sftp*`, damit der Paritätstest sie findet (T5 hatte ihn gebrochen, `sftp.rs` steht jetzt in `RUST_FILES`); das Verify ist um `desktop-ui` erweitert. Die SFTP-Argumente entstehen beim Start der Sitzung (`with_sftp`) und liegen in `Session.sftp`.
- T6: Tauri meldet einen Drop selbst als `tauri://drag-drop` mit den Pfaden an die Webview; geschützt ist nur, dass die Webview für einen Upload keinen Pfad nennt, sondern Rust die Pfade unter der Nummer hält (Prüfer).
- T7: Ein Drop aufs Hauptfenster geht an das Dateien-Panel des sichtbaren Tabs, wenn es offen ist und die Sitzung läuft; Rust filtert nicht nach der Position im Fenster, ein Drop anderswo im Fenster lädt also in den gezeigten Ordner hoch. Läuft dort gerade eine Aktion, meldet das Panel das und lädt nichts.
- T7: Ein Link wird wie eine Datei heruntergeladen (das Ziel), nicht betreten. Namen vom Host werden nur in der Anzeige um Steuer- und Bidi-Zeichen bereinigt (U+FFFD), gesendet wird der rohe Name.
- T7: Der Hinweis auf Schlüssel oder Agent erscheint nur unter Windows (`navigator.userAgent`) bei `ERR_CONNECTION`, solange in der Sitzung noch keine Aktion gelungen ist: dort meldet sich der SFTP-Kanal ohne ControlMaster selbst an, und Rust meldet auch spätere Absagen des Hosts (Rechte, fehlende Datei) als `ERR_CONNECTION` (Prüfer). Ein eigener Code für das Scheitern von `Channel::open` hätte die T6-Dateien berührt. Größen stehen nur bei Dateien (Rust liefert für Links und Sonstiges 0).
