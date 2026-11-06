<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-terminal-2 — Snippets, Broadcast und SFTP im eingebetteten Terminal

Roadmap R-1071, R-1072 (Zug `tasks/kern-terminal-2.md`). Baut auf dem eingebetteten SSH-Terminal (R-1069,
`docs/features/arch-ssh-terminal.md`) und dem abgedockten Fenster (R-1070, `docs/features/kern-terminal-1.md`) auf.
Vorlage ist das Mockup AdminCave/DesignSystem@244e890 (`ui_kits/adminhelper/terminal.jsx`, Panels `snippets` und
`files`, `data.js` `snippets`). Kevins Entscheidungen vom 2026-11-06 stehen in den Notizen der Roadmap-Zeilen. Stand
`origin/main@aa939d1c`.

## Problem / Motivation
- **R-1071:** Wiederkehrende Befehle tippt man in jeder Sitzung neu. Will man denselben Befehl auf mehreren Servern
  ausführen, muss man jeden Tab einzeln öffnen. Der Kopf einer Sitzung (`SshTerminal.svelte`) hat nur Schrift,
  Terminal-Optionen, Neu verbinden und Schließen. Das Seitenpanel (`term-panel`) zeigt nur die Optionen.
- **R-1072:** Wer eine Datei auf den Server bringen oder holen will, braucht ein zweites Werkzeug (scp, WinSCP).
  Der Desktop startet `ssh` im Pseudo-Terminal (`commands.rs` `ssh_spawn`, `pty.rs`). Einen Dateikanal neben der
  Shell gibt es nicht.

## Ziel & Nicht-Ziele
Ziel (R-1071, Snippets):
- Der Kopf einer Sitzung bekommt den Knopf **Snippets**. Er öffnet ein Seitenpanel. Das Panel und das der
  Terminal-Optionen schließen sich gegenseitig aus, wie im Mockup.
- Das Panel zeigt die Snippet-Liste. Jede Karte trägt einen Namen und `$ <Befehl>`. Ein Klick schreibt den Befehl
  und `Enter` in die aktive Sitzung, ein mehrzeiliger Befehl geht Zeile für Zeile. Läuft die Sitzung nicht mehr,
  passiert nichts; die Karten sind dann deaktiviert.
- Über **Neu** legt man ein Snippet an, über die Karte bearbeitet oder löscht man es (Name und Befehl, Löschen mit
  Rückfrage).
- Die Snippets gelten je Workspace und liegen lokal in dessen `workspace.json`, wie die Favoriten. Solange ein
  Workspace keine eigene Liste hat, zeigt das Panel die Standardliste aus dem Mockup, in der Sprache der Oberfläche
  (Speicher prüfen `df -h`, RAM & Swap `free -h`, Laufzeit & Last `uptime`, Container `docker ps`, nginx-Status
  `systemctl status nginx`, Fehlgeschlagene Units `systemctl --failed`, Letzte Logins `last -n 5`). Die erste
  Änderung speichert die ganze Liste; eine leere Liste bleibt leer.
- **Broadcast:** Die Checkbox „An alle SSH-Sitzungen senden“ (Hinweis „Broadcast — mit Bedacht benutzen.“) lässt
  einen Snippet-Klick an alle laufenden SSH-Sitzungen dieses Workspace gehen, in jedem Tab und in jedem abgedockten
  Fenster. Ansible-Sitzungen und beendete Sitzungen bekommen nichts. Solange die Checkbox an ist, steht in der
  Fußzeile jeder Sitzung in Warnfarbe „● Broadcast aktiv“. Die Checkbox gilt nur bis zum Ende der App und ist beim
  Start aus. Getippte Tasten gehen nie an mehrere Sitzungen.

Ziel (R-1072, SFTP):
- Der Kopf einer Sitzung bekommt den Knopf **Dateien (SFTP)**. Er öffnet ein Seitenpanel, das sich wie die anderen
  beiden ausschließt. Oben steht der Pfad als Pill, beim Öffnen das Home-Verzeichnis (`.` aufgelöst). Darunter liegt
  die Liste: Ordner zuerst, dann Dateien, je mit Symbol, Name und Größe.
- Ein Klick auf einen Ordner wechselt hinein, `..` geht eine Ebene hoch. Ein Klick auf eine Datei lädt sie herunter;
  den Zielort wählt der Speichern-Dialog des Betriebssystems.
- **Hochladen** öffnet den Datei-Dialog des Betriebssystems (mehrere Dateien). Dateien, die man auf das Panel zieht,
  lädt der Desktop ebenfalls hoch (Drop-Zone „Dateien hierher ziehen zum Hochladen“). Das Ziel ist immer der
  angezeigte Ordner, eine vorhandene Datei gleichen Namens wird erst nach Rückfrage ersetzt.
- **Neuer Ordner** fragt den Namen und legt ihn an. **Aktualisieren** liest den Ordner neu.
- Hoch- und Herunterladen zeigen den Fortschritt (Bytes von Gesamt) im Panel. Ein Fehler steht als Meldung im Panel,
  die Sitzung läuft weiter.
- **Transport:** `ssh -s <ziel> sftp` vom System-OpenSSH, über dessen stdin/stdout spricht ein SFTP-Client in Rust
  (`russh-sftp`). Unter Linux und macOS läuft der Kanal über den ControlMaster der Terminal-Sitzung: keine zweite
  Anmeldung, auch nicht bei Passwort oder Sprunghost. Unter Windows kann OpenSSH kein ControlMaster
  (PowerShell/Win32-OpenSSH#405); dort meldet sich der Kanal je Aktion neu an, nur mit Schlüssel oder Agent
  (`BatchMode=yes`). Scheitert das, sagt ein Hinweis im Panel, dass SFTP unter Windows einen Schlüssel oder den Agent
  braucht.

Nicht-Ziele:
- Snippets am Server oder geräteweit, Snippet-Variablen, Import und Export.
- Broadcast getippter Tasten, Broadcast über Workspaces hinweg.
- Snippets und SFTP im abgedockten Fenster: Wie die Terminal-Optionen bleiben sie dem Hauptfenster vorbehalten
  (`SshTerminal.svelte`, Kopfkommentar: das Fenster darf nichts speichern und nichts starten).
- SFTP: Ordner rekursiv hoch- oder herunterladen, Löschen, Umbenennen, Rechte ändern, Ziehen aus dem Panel heraus.
  Das Mockup zeigt nichts davon. Gezogene Ordner lehnt der Upload mit einer Meldung ab.
- SFTP für Ansible-Sitzungen und für SSH im OS-Terminal.
- Ein Abbrechen-Knopf für laufende Übertragungen (das Schließen der Sitzung beendet sie).

## Betroffene Komponenten & Dateien
- Desktop (Rust):
  - `apps/desktop/src-tauri/src/models.rs` (`Settings`, ab Zeile 255) und `workspace.rs` (`Meta`, ab Zeile 348):
    neues Feld `snippets`. Dazu `storage.rs` (Zeile 403/468, meta ↔ Settings) und die Konstruktoren mit allen
    Feldern (`commands.rs`, `migration.rs`, `workspace.rs`, `storage.rs`).
  - `pty.rs`: `Spawn` (Zeile 58) bekommt `broadcast: bool`, `PtyRegistry` (Zeile 138) die Methode `broadcast`.
  - `commands.rs`: `ssh_spawn` (Zeile 688) setzt `broadcast` und, unter Unix, die ControlMaster-Argumente. Neu sind
    `terminal_broadcast` und die SFTP-Befehle. `save_settings` prüft die Snippets.
  - `connection/ssh.rs`: `build_ssh_args` (Zeile 22) und `push_option_args` (Zeile 70). Neu ist die Variante für
    den SFTP-Kanal: ohne Weiterleitungen (`-L/-R/-D`) und ohne `ForwardAgent`.
  - `ansible.rs`: `create_run_dir` (Zeile 130) wird für das ControlPath-Verzeichnis mitbenutzt.
  - Neu `src/sftp.rs`: Kanal starten, Ordner lesen, Ordner anlegen, hoch- und herunterladen.
  - `main.rs` (Befehle, Drag-and-Drop-Ereignis), `build.rs` (`AppManifest::commands`), `capabilities/default.json`.
  - `Cargo.toml` (Zeile 30: tokio bekommt `process`, `io-util`; neu `russh-sftp`) und `Cargo.lock`.
- Desktop (UI):
  - `ui/src/components/terminal/SshTerminal.svelte` (Kopfknöpfe, Panel, Fußzeile).
  - Neu `ui/src/components/terminal/SnippetsPanel.svelte` und `FilesPanel.svelte`, je mit Test.
  - `ui/src/lib/stores/terminals.ts` (Broadcast-Schalter), `ui/src/lib/bridge/index.ts` und `types.ts`,
    `ui/src/lib/i18n/dictionaries.ts`.
- E2E: `apps/desktop/e2e/test/specs/ssh-connect.live.js`.
- `THIRD_PARTY_LICENSES.md` (russh-sftp), Doku (siehe unten).

## Datenmodell / API / Migrationen
- Keine Migration. `workspace.json` bekommt `snippets: [{name, command}]`, fehlt es, ist es `null`
  (`serde(default)`). `null` heißt Standardliste, `[]` heißt leer. `Settings` trägt das Feld unverändert zur UI
  (`types.ts`). Ältere Versionen ignorieren das Feld.
- Grenzen, geprüft in `save_settings`: höchstens 200 Snippets, Name 1–64 Zeichen, Befehl 1–4096 Zeichen; keine
  Steuerzeichen außer Zeilenumbruch und Tab im Befehl, keine im Namen. Eine Verletzung lehnt das Speichern ab.
- **Tauri-IPC, neu (nur Fenster `main`, `capabilities/default.json`):**
  - `terminal_broadcast(data: Vec<u8>) -> u32`: schreibt an alle laufenden Sitzungen mit `broadcast` und meldet
    ihre Zahl.
  - `sftp_list(session, path) -> {path, entries: [{name, kind, size}]}`: `path` ist der aufgelöste Pfad.
  - `sftp_mkdir(session, path)`.
  - `sftp_upload(session, dir, progress: Channel) -> u32`: öffnet den Datei-Dialog in Rust, lädt die gewählten
    Dateien hoch, meldet die Zahl. `sftp_upload_dropped(session, dir, drop, progress)`: lädt die Dateien hoch, die
    zuletzt auf dieses Fenster gezogen wurden. `drop` ist die Nummer aus dem Ereignis.
  - `sftp_download(session, path, progress) -> bool`: öffnet den Speichern-Dialog in Rust; `false` heißt abgebrochen.
  - Ereignis `sftp-drop {drop, names}` an das Fenster, auf das Dateien gezogen wurden.
  - `session` ist die Id der Terminal-Sitzung; der Befehl nimmt deren Verbindung und deren ControlPath, nie Werte aus
    der Webview.
- Lokale Pfade kommen nie aus der Webview: Datei-Dialog, Speichern-Dialog und gezogene Dateien liest Rust selbst.
  So kann eine kompromittierte Webview keine beliebige lokale Datei auf einen Server laden.
- Kein Vertrag mit Server, Web oder Agent ändert sich.

## Externe Integrationen
- OpenSSH `ssh_config(5)`: `ControlMaster`, `ControlPath`, `ControlPersist`, `BatchMode`; `ssh(1)` `-s` (Subsystem).
  Auf der Kommandozeile gesetzte Optionen gehen der Konfigurationsdatei vor (der erste Wert gilt). Ein Master mit
  `ControlPersist=no` endet erst, wenn auch die letzte Sitzung über ihn endet.
  Unix-Sockets haben eine Pfadgrenze von etwa 104 Bytes (macOS) bzw. 108 Bytes (Linux); das Verzeichnis bekommt
  daher einen kurzen Namen. Unter macOS liegt `temp_dir()` tief in `/var/folders/…`; ob der Pfad dort reicht, ist
  nicht verifiziert. T4 prüft die Länge und fällt sonst auf `/tmp` zurück.
- Win32-OpenSSH: kein ControlMaster (Issue PowerShell/Win32-OpenSSH#405 offen, openssh-portable#863 nicht gemergt).
- `russh-sftp` 3.0.1 (Apache-2.0, <https://docs.rs/russh-sftp>): `SftpSession::new(stream)` über einen beliebigen
  `AsyncRead + AsyncWrite`, Methoden `read_dir`, `create_dir`, `open`, `create`, `canonicalize`, `metadata`. Der
  Client hängt nicht an `russh`.
- Tauri v2: Drag-and-Drop (`WindowEvent::DragDrop`, `DragDropEvent::Drop { paths, position }`, standardmäßig an),
  `tauri-plugin-dialog` (Rust: `DialogExt::dialog().file().blocking_pick_files()`, `blocking_save_file()`, nicht auf
  dem Hauptthread aufrufen), `ipc::Channel`.

## Trade-offs & Alternativen
- **Snippets lokal je Workspace** (Kevin): kein Server-Vertrag und keine Migration; dafür kein Abgleich zwischen
  Geräten.
- **`None` heißt Standardliste:** Die Namen der Standardliste folgen der Sprache, solange niemand die Liste ändert.
  Die Alternative, die Liste beim ersten Start zu schreiben, legte die Sprache dieses Moments fest.
- **Broadcast nur für Snippets** (Kevin): Getippte Tasten an mehrere Server sind leicht ein Unfall; ein Snippet ist
  ein bewusster Klick mit sichtbarem Befehl.
- **Broadcast in Rust** (`terminal_broadcast` über die ganze Registry) statt einer Schleife über
  `terminal_write` in der UI: Nur die Registry weiß sicher, welche Sitzung `ssh` ist und noch läuft, auch in
  abgedockten Fenstern. Ein Befehl, nur für `main`.
- **SFTP über das System-OpenSSH** (Kevin) statt eines SSH-Clients in Rust: Hostschlüssel, `~/.ssh/config`, Agent,
  Sprunghosts und Schlüssel gelten wie im Terminal; kein zweiter `known_hosts`. Über den ControlMaster braucht es
  keine zweite Anmeldung. Kosten: unter Windows nur mit Schlüssel oder Agent.
- **Ein Kanal je Aktion** statt eines dauerhaften: Ein offener SFTP-Kanal hielte den Master am Leben, nachdem die
  Shell mit `exit` endet, und die Sitzung bliebe „verbunden“. Je Aktion kostet unter Linux nur das Öffnen eines
  Kanals im Master; unter Windows eine Anmeldung.
- **Pfade nur aus Rust:** Mehr Code (Dialog und Drop in Rust), aber die Webview bekommt keinen Lesezugriff auf das
  lokale Dateisystem.

## Risiken & Rollback
- **ControlMaster ändert die Terminal-Sitzung:** `ssh` legt unter Unix jetzt einen Socket an. Verbindet `ssh` nicht,
  bleibt die Sitzung wie bisher. Hält ein SFTP-Kanal den Master nach `exit` offen, endet er mit der Aktion. Setzt
  die `~/.ssh/config` des Nutzers eigene `ControlMaster`/`ControlPath`, gelten unsere Kommandozeilen-Optionen. Den
  Socket und sein Verzeichnis entfernt `Spawn.cleanup` nach dem Ende der Sitzung.
- **Broadcast** schickt einen Befehl an viele Server: sichtbare Warnung, nur Snippets, Checkbox beim Start aus. Der
  Befehl `terminal_broadcast` ist nur im Hauptfenster erlaubt.
- **SFTP:** Ein Upload überschreibt nur nach Rückfrage. Eine kompromittierte Webview könnte über `sftp_list` und
  `sftp_download` mit Dialog Dateien des Servers anzeigen bzw. nach Bestätigung im Dialog speichern; das kann sie
  über das Terminal heute schon. Den Datei-Inhalt und die Pfade schreibt der Desktop in kein Log.
- **Neue Abhängigkeit** `russh-sftp` (Apache-2.0, in `THIRD_PARTY_LICENSES.md`); `cargo audit` fährt in der CI.
- **Windows:** Der Kanal mit zweiter Anmeldung ist nur über die CI-Jobs `rust-windows` und `tauri-build-smoke`
  geprüft, wie R-1069/R-1070. Die Oberfläche unter Windows bleibt nicht verifiziert.
- Rollback per Revert der Task-Commits. `snippets` in `workspace.json` ignoriert eine ältere Version.

## Doku-Impact
`docs/admin/index.html` DE und EN (SSH-Terminal: Snippets, Broadcast, Dateien), `docs/developer/desktop.html` DE und
EN (IPC-Tabelle, Abschnitt Terminal: Broadcast, ControlMaster, SFTP-Kanal, Pfade nur aus Rust, Settings-Feld
`snippets`), `THIRD_PARTY_LICENSES.md`, `changelog.d/kern-terminal-2.md`.

## Offene Fragen
Keine aus Kevins Bereich: Speicherort, Klick-Verhalten, Broadcast-Umfang und Transport hat Kevin am 2026-11-06
entschieden. Eigene Entscheidungen (im Ledger unter `## Entscheidungen`): Standardliste bei `null`, Grenzen der
Snippets, Broadcast-Checkbox nicht gespeichert, ein SFTP-Kanal je Aktion, kein Löschen und Umbenennen,
Überschreiben nach Rückfrage, Pfade nur aus Rust.
