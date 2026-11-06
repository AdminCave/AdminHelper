<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-terminal-1 — Sitzungen abdocken, Ansible im eingebetteten Terminal

Roadmap R-1070, R-1073 (Zug `tasks/kern-terminal-1.md`). Baut auf dem eingebetteten SSH-Terminal aus R-1069
(`docs/features/arch-ssh-terminal.md`) auf. Vorlage ist das Mockup AdminCave/DesignSystem@244e890
(`ui_kits/adminhelper`: `chrome.jsx` `SessionTabs`/`FloatWindow`, `terminal.jsx`, `ops.jsx` `AnsibleView`, README
„Sitzungs-Tabs“). Kevin hat am 2026-11-02 entschieden, dass eine abgedockte Sitzung ein echtes Tauri-Fenster wird und
kein Panel. Stand `origin/main@79878e61`.

## Problem / Motivation
- **R-1070:** Eine Sitzung des eingebetteten Terminals lebt nur als Tab im Hauptfenster. Ein Fenster gibt es nur
  einmal: `main.rs` baut `WebviewWindowBuilder::new(app, "main", …)`, `tauri.conf.json` hat `windows: []`. Die
  Ausgabe einer Sitzung geht über einen `Channel` an genau die Webview, die sie geöffnet hat
  (`commands.rs` `terminal_open_ssh`). Liest dort niemand mehr, beendet `PtyRegistry` das Programm (`pty.rs`, Sink
  gibt `false`). Beim Start der UI beendet `closeAllTerminals` alle Sitzungen des Prozesses (`ui/src/main.ts:21`).
  Sitzungen gehen beim App-Neustart verloren.
- **R-1073:** Ein Ansible-Lauf öffnet immer ein OS-Terminal (`ansible.rs` `launch_ansible` → `start_in_terminal`).
  Einen Probelauf (`--check`) gibt es nicht. Die Konsolen-Einstellung (`Settings.ssh_console`, `Embedded` ist
  Standard) gilt nur für SSH.

## Ziel & Nicht-Ziele
Ziel:
- **Abdocken:** Ein SSH-Tab lässt sich auf drei Wegen in ein eigenes OS-Fenster abdocken: per Knopf im Tab, per
  Doppelklick auf den Tab oder indem man den Tab nach unten zieht (Mockup). Das Fenster zeigt nur das Terminal mit
  Titel und dem Knopf *Andocken*. Im Hauptfenster bleibt der Tab kursiv mit einem Symbol stehen; ein Klick darauf
  holt das abgedockte Fenster nach vorn.
- **Andocken** holt die Sitzung als Tab zurück. Das Programm läuft beim Ab- und Andocken weiter, nichts startet neu.
  Das neue Fenster bekommt zuerst die letzte Ausgabe aus einem Ringpuffer der Sitzung im Backend, danach die
  laufende.
- **Fensterrechte je Label:** Ein abgedocktes Fenster (Label `terminal-<id>`) darf nur die Terminal-Befehle seiner
  eigenen Sitzung aufrufen, dazu das Lesen der Einstellungen (Schrift, Farbschema) und Ereignisse. Alles andere ist
  dem Hauptfenster vorbehalten (`main`): Anmeldung, Verbindungen, Tunnel, Ansible, Workspaces.
- **Wiederherstellen:** Die Einstellung „Letzte Sitzungen beim Start wiederherstellen“ öffnet beim Start der UI die
  Verbindungen neu, deren SSH-Tabs beim Beenden offen waren (neue SSH-Verbindung, gleiche Reihenfolge). Es wird
  keine laufende Sitzung über einen Neustart gerettet.
- **Ansible:** Folgt die Konsolen-Einstellung dem eingebetteten Terminal, läuft `ansible-playbook` in einem neuen Tab
  mit Live-Ausgabe; sonst wie bisher im OS-Terminal. Neu ist der Schalter „Probelauf (`--check`)“ auf der
  Ansible-Seite, der für beide Wege gilt. Das Run-Verzeichnis (Inventar, Playbook) wird gelöscht, sobald der Lauf
  endet, wie heute.

Nicht-Ziele:
- RDP-Sitzungen abdocken: Das eingebettete RDP hat noch keine Oberfläche (`kern-rdp-1`); die Fenster-Mechanik aus
  diesem Zug wird dort mitbenutzt.
- Sitzungen über einen Neustart der App am Leben halten: Dafür bräuchte es einen Dienst außerhalb des App-Prozesses.
- Mehrere Sitzungen in einem abgedockten Fenster, Position und Größe des Fensters merken, Snippets und SFTP aus dem
  Mockup.
- Ansible „erneut ausführen“ aus dem Tab: Ein neuer Lauf startet von der Ansible-Seite.

## Betroffene Komponenten & Dateien
- Desktop (Rust):
  - `apps/desktop/src-tauri/src/pty.rs`: Ringpuffer je Sitzung, austauschbarer Sink, Besitzer-Fenster.
  - `src/commands.rs`: `terminal_open_ssh` merkt sich das aufrufende Fenster. Neu sind `terminal_attach`,
    `terminal_detach`, `terminal_dock` und `terminal_open_ansible`. `terminal_close_all` gilt nur noch für die
    Sitzungen des aufrufenden Fensters.
  - `src/main.rs`: Befehle registrieren, Fensterereignisse abgedockter Fenster.
  - `src/ansible.rs`: Start im Pseudo-Terminal, `--check`.
  - `src/models.rs`: zwei neue Einstellungen.
  - `build.rs` (`AppManifest::commands`), `capabilities/default.json`, neue `capabilities/terminal-window.json`.
- Desktop (UI):
  - `ui/src/lib/stores/terminals.ts` und `ui/src/lib/bridge/index.ts`.
  - `ui/src/components/AppShell.svelte` (Tabs) und `ui/src/components/terminal/SshTerminal.svelte`.
  - `ui/src/main.ts` (Einstieg des abgedockten Fensters) und eine neue Komponente für das abgedockte Fenster.
  - `ui/src/pages/Ansible.svelte`, `ui/src/lib/stores/ansible.ts`.
  - `ui/src/components/settings/TerminalSection.svelte`.
- E2E: `apps/desktop/e2e/test/specs/ssh-connect.live.js`, gefahren von `scripts/tests/desktop_e2e_connect.sh`.
- Doku: `docs/developer/desktop.html` DE und EN, `changelog.d/kern-terminal-1.md`.

## Datenmodell / API / Migrationen
- Keine Migration.
- Neu sind `restoreSessions: bool` in `prefs.json` (global, für das Gerät) und `openSessions: string[]`
  (Verbindungs-IDs) im `workspace.json` des Workspace. Fehlen sie, gilt der
  Standardwert (`serde(default)`), alte Dateien laden also weiter.
- **Tauri-IPC, neu:**
  - `terminal_attach(id, output)`: schickt zuerst den Ringpuffer, dann die laufende Ausgabe; der Aufrufer wird
    Besitzer.
  - `terminal_detach(id, title)`: öffnet das Fenster `terminal-<id>`; nur aus `main`.
  - `terminal_dock(id)`: schließt es und meldet `terminal-docked {id}` an `main`.
  - `terminal_open_ansible(playbookId, targets, check, cols, rows, output) -> u64`.
  - `ansible_run` bekommt `check`.
- **Tauri-IPC, geändert:** `terminal_write`, `terminal_resize` und `terminal_close` lehnen eine fremde Sitzung ab,
  wenn sie aus einem `terminal-*`-Fenster kommen. Kein Vertrag mit Server, Web oder Agent ändert sich.

## Externe Integrationen
- Tauri v2: `WebviewWindowBuilder`, `Window::label`, `WindowEvent::CloseRequested`/`Destroyed`, `Emitter::emit_to`.
- Capabilities (<https://v2.tauri.app/security/capabilities/>): App-Befehle sind ohne `AppManifest::commands` in
  `build.rs` in jedem Fenster erlaubt. Erst mit der Liste braucht jedes Fenster die Rechte
  `allow-<befehl>`. Die Grenzen hängen am Label, nicht am Titel. Ob `"windows": ["terminal-*"]` ein Glob ist, sagt
  die Seite nicht (nicht verifiziert, in T2 im Schema von `tauri-utils` nachlesen). Deshalb prüft jeder
  Terminal-Befehl zusätzlich das Label des Aufrufers.
- `ansible-playbook --check`: Probelauf ohne Änderungen (Ansible-Doku „Validating tasks: check mode“).

## Trade-offs & Alternativen
- **Ringpuffer im Backend statt Puffer in der Webview:** Ein neues Fenster ist eine neue Webview ohne den Zustand der
  alten. Den Verlauf hat nur das Backend. Der Puffer fasst 1 MiB je Sitzung; das sind bei 80 Spalten gut 10 000
  Zeilen, mehr als der Standard-Scrollback (`TerminalPrefs`). Empfohlen.
- **Ein Fenster je Sitzung** (Label `terminal-<id>`) statt eines zweiten Fensters mit Tabs: so passt es zum Mockup,
  und die Rechte bleiben einfach. Empfohlen.
- **Rechte doppelt gesichert** (Capability und Label-Prüfung im Befehl): Die Capability allein hinge am ungeprüften
  Glob. Empfohlen.
- **Ansible als eigener Sitzungstyp im selben Store** statt einer eigenen Ausgabe-Ansicht: Tab, Abdocken und
  Ringpuffer gibt es damit ohne Zusatzaufwand.

## Risiken & Rollback
- **Rechte:** `AppManifest::commands` macht jeden App-Befehl genehmigungspflichtig. Vergisst `default.json` einen,
  scheitert er im Hauptfenster. Ein Test vergleicht deshalb die Liste in `build.rs` mit `generate_handler!` und mit
  `default.json` (Risikopfad, `security`).
- **Eingaben aus dem abgedockten Fenster:** Es erreicht nur die eigene Sitzung (Label-Prüfung).
- **Ringpuffer im Speicher:** Er kann Passwörter enthalten, die das Programm angezeigt hat, nicht aber getippte
  Eingaben: Die Shell hallt ein Passwort nicht wider, und der Puffer liegt nur im RAM. `pty.rs` loggt weiter nichts.
- **Windows:** ConPTY und die Fenster sind dort nur über die CI-Jobs `rust-windows` und `tauri-build-smoke` geprüft.
  Die Oberfläche unter Windows bleibt nicht verifiziert.
- Rollback per Revert der Task-Commits. Die neuen Felder in `prefs.json` und `workspace.json` ignoriert eine ältere Version.

## Doku-Impact
`docs/developer/desktop.html` DE und EN: Abschnitt zum eingebetteten Terminal (Abdocken, Ringpuffer, Fensterrechte,
Wiederherstellen, Ansible im Tab). Dazu `changelog.d/kern-terminal-1.md`. Eine Nutzerseite zum Terminal gibt es
nicht; README nennt die Einstellungen (Abschnitt Terminal).

## Offene Fragen
1. **Schließen des abgedockten Fensters über die Titelleiste** (das X des Systems): Soll das die Sitzung andocken
   oder beenden? Empfehlung: andocken. Dann geht kein laufendes Programm durch einen Fehlgriff verloren. Beenden
   bleibt über das X am Tab. Im Mockup beendet das X die Sitzung, dort ist es aber ein Panel ohne Fensterrahmen.
   Betrifft T4.
2. **Standardwert „Letzte Sitzungen beim Start wiederherstellen“:** Empfehlung: aus. Ein Start soll ohne Zutun keine
   SSH-Verbindung aufbauen. Betrifft T6, T7.
