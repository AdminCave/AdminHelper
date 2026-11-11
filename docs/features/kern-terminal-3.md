# Desktop-Terminal: Dateien, Befehle, Einfügen, Sitzungsverlauf (kern-terminal-3)

Roadmap: R-1170, R-1171, R-1174, R-1155, R-1165, R-1166, R-1144, R-1175, R-1159 (Kevin 2026-11-09 Triage, seit
2026-11-10 vor dem Release 0.47.0). R-1164 fährt nicht mit: `apps/desktop/src-tauri/src/pty.rs` ändert der offene
Branch `feature/klein-kommentare-desktop-1`, die Zeile wandert nach `tasks/kern-terminal-4.md`.

## Problem / Motivation
Nachlese aus kern-terminal-1/-2 und arch-ssh-terminal: Funde aus Reviews am eingebetteten Terminal, seinem
Dateien-Panel und seinen Befehlen.

- **R-1170:** Der SFTP-Download legt seine Teildatei `.<name>.ah-part` mit `File::create` an
  (`apps/desktop/src-tauri/src/sftp.rs:393`). Sie soll exklusiv neu angelegt werden.
- **R-1171:** Der Dateiname, den der Speichern-Dialog vorschlägt, kommt ungeprüft vom Server
  (`sftp::remote_name`, `commands.rs:1135`). Er soll bereinigt werden.
- **R-1174:** Das Dateien-Panel lädt, sobald die Sitzung läuft, also schon während der Passwortabfrage
  (`FilesPanel.svelte:187`). Der ControlMaster-Socket fehlt dann noch: `sftp` meldet sich selbst an oder scheitert,
  und der Nutzer muss nach der Anmeldung von Hand aktualisieren.
- **R-1155:** `terminal::which` (`terminal.rs:27`) nimmt den ersten Treffer im PATH, auch aus einem relativen Eintrag.
  `ssh_spawn` verwirft ihn (nur absolute Pfade), statt den nächsten absoluten Eintrag zu nehmen: Der Start scheitert.
- **R-1165:** `terminal_open_ssh` prüft das Fenster nicht, aus dem es aufgerufen wird; `terminal_open_ansible` und die
  übrigen Terminal-Befehle tun das.
- **R-1166:** `ansible_run` nimmt `check: Option<bool>`; die UI schickt den Wert immer.
- **R-1144:** Mehrzeiliger Text wird ohne Rückfrage eingefügt; jede Zeile wird sofort ausgeführt.
- **R-1175:** Ein Snippet im Broadcast-Modus an null Sitzungen meldet nichts (`runSnippet`, `terminals.ts:1063`).
- **R-1159:** Ein Start im eingebetteten SSH-Terminal beginnt einen Eintrag im Sitzungsverlauf
  (`connectEmbedded` → `markConnectionUsed`), beendet ihn aber nie. Der erste Teil der Zeile (Neuladen der Liste) ist
  mit 133a6fc4d behoben.

## Ziel & Nicht-Ziele
Ziel: die neun Zeilen beheben, je mit Test.
Nicht-Ziele: kein neues Verhalten des OS-Terminals; keine Änderung am Sitzungsverlauf eingebetteter RDP-Tabs (ein
gleicher Befund dort wird eine eigene Roadmap-Zeile); R-1164.

## Betroffene Komponenten & Dateien
- Desktop-Backend: `apps/desktop/src-tauri/src/sftp.rs`, `commands.rs`, `terminal.rs`, `models.rs`.
- Desktop-UI: `apps/desktop/ui/src/components/terminal/SshTerminal.svelte`, `FilesPanel.svelte` (nur falls nötig),
  `components/settings/*` (Einstellung), `lib/models/settings.ts`, `lib/bridge/types.ts`, `lib/stores/terminals.ts`,
  `lib/stores/connectFlow.ts`, `lib/i18n/dictionaries.ts`, Tests daneben.

## Datenmodell / API / Migrationen
- Kein Server, keine Migration.
- Tauri-IPC: `ansible_run` verlangt `check` (bool). Der einzige Aufrufer (`bridge/index.ts:536`) schickt ihn immer.
- `TerminalPrefs` bekommt ein Feld für die Rückfrage beim Einfügen. Ein fehlendes Feld in `prefs.json` nimmt seinen
  Standard (serde default, wie die übrigen Felder).

## Externe Integrationen
OpenSSH `ControlPath`/`ControlMaster` (ssh_config(5)): Der Master-Socket entsteht erst nach der Anmeldung. Das
SFTP-Kommando wartet deshalb auf ihn (T3), statt sich selbst anzumelden.

## Trade-offs & Alternativen
- **R-1174:** (a) Rust wartet im SFTP-Befehl, bis der Socket da ist (Polling, gedeckelt, Abbruch bei Sitzungsende) —
  die UI bleibt unverändert und zeigt solange „lädt“; (b) die UI fragt die Bereitschaft ab und lädt neu. Empfehlung
  und Wahl: (a), ein Ort, keine neue IPC.
- **R-1155:** `which` überspringt relative PATH-Einträge für alle Aufrufer (Launcher, xfreerdp, ansible-playbook).
  Ein Programm aus einem relativen PATH-Eintrag hängt vom Arbeitsverzeichnis der App ab; das will kein Aufrufer.
- **R-1165:** Erlaubt sind das Hauptfenster und ein losgelöstes Terminal-Fenster (`terminal-<id>`): Dessen
  „Neu verbinden“ ruft `terminal_open_ssh` aus diesem Fenster auf (`DetachedTerminal.svelte` → `SshTerminal`).
  „Nur main“ würde das brechen.
- **R-1144:** Die Rückfrage ist eine Einstellung, Standard an (wie die Warnung beim mehrzeiligen Einfügen in
  verbreiteten Terminals); ausschaltbar in den Terminal-Einstellungen.
- **R-1159:** Der Eintrag endet, wenn das Programm des Tabs endet oder der Tab geschlossen wird, einmal. Ein
  „Neu verbinden“ beginnt keinen neuen Eintrag (wie heute).

## Risiken & Rollback
Jede Task ist ein eigener Commit und einzeln zurücknehmbar. Risiko R-1174: Ein Socket, der nie entsteht (Anmeldung
abgebrochen), lässt den Befehl bis zum Deckel warten; danach ein Fehler mit Hinweis.

## Doku-Impact
`docs/admin/index.html` und `docs/en/admin/index.html` (Terminal: Einfügen-Rückfrage, Dateien-Panel wartet auf
Anmeldung), `docs/developer/desktop.html` und `docs/en/developer/desktop.html`
(IPC `ansible_run`, Fensterprüfung), `changelog.d/kern-terminal-3.md`.

## Offene Fragen
Keine.
