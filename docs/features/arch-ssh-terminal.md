# Eingebettetes SSH-Terminal mit Sitzungs-Tabs

Roadmap R-1069 (FEAT) · Branch `feature/arch-ssh-terminal` · Ledger `tasks/arch-ssh-terminal.md`
Quelle: Kevin 2026-11-02 (PTY + System-OpenSSH), Design-Mockup `AdminCave/DesignSystem@244e890`
(`ui_kits/adminhelper/terminal.jsx`, `chrome.jsx` `SessionTabs`, `connections.jsx` `ConnectMenu`,
`settings.jsx` Terminal-Sektion). Hängt ab von R-1062 (Shell, gemergt #374) und R-1041 (Crates, gemergt #369).

## Problem / Motivation

SSH startet heute ein fremdes Programm: unter Linux das erste gefundene Terminal mit
`bash -c 'ssh …; read'` (`apps/desktop/src-tauri/src/connection/ssh.rs:54`, `terminal.rs` `open_linux_terminal`),
unter Windows Windows Terminal oder cmd (`open_windows_terminal`). Die App sieht von der Sitzung nichts: kein Status,
kein Neu verbinden, jede Sitzung ein eigenes Fenster irgendwo auf dem Desktop, ohne Terminal-Emulator gar keine
Sitzung. Das Mockup führt Sitzungen als Tabs neben der Seite, mit Status und Terminal-Optionen. R-1070 (Abdocken),
R-1071 (Snippets/Broadcast), R-1072 (SFTP), R-1073 (Ansible-Live-Ausgabe) und R-1098 (eingebettetes RDP) bauen auf
dieser Sitzung im Backend und der Tab-Leiste auf.

## Ziel & Nicht-Ziele

**Ziel** (sichtbar):
- **Konsole wählen:** neue globale Einstellung *Konsole für SSH*: **AdminHelper-Terminal** (eingebettet, Tab) oder
  **OS-Terminal** (der heutige Weg, unverändert). Standardwert entscheidet Kevin (Offene Fragen, Ledger T3).
- **Split-Button** im Inspector der Verbindungsliste (`ConnectionInspector.svelte:89`): Hauptknopf *Verbinden* nimmt
  die Einstellung; der Pfeil öffnet ein Menü *Im AdminHelper-Terminal* / *Im OS-Terminal*, das nur diesen Start
  abweichen lässt. Nur bei SSH-Verbindungen; RDP und Web behalten den einfachen Knopf. Doppelklick, Enter,
  Schnellzugriff, Dashboard und Befehlspalette nehmen die Einstellung.
- **Tab-Leiste** unter dem Header, sobald mindestens eine Sitzung offen ist (wie `chrome.jsx` `SessionTabs`):
  erster Tab ist die aktuelle Seite (Icon + Seitenname), dann je Sitzung Typ-Icon, Name, Status-Punkt
  (verbinde/verbunden/getrennt) und Schließen. Ein Klick in die Sidebar holt die Seite nach vorn. Inaktive Sitzungen
  bleiben gemountet (Inhalt und Scrollback bleiben), nur unsichtbar. Der Header zeigt bei aktiver Sitzung deren
  Namen und `SSH · <host>`; die Statusleiste unten zählt die offenen Sitzungen.
- **Terminal** (xterm.js im Webview): Kopfzeile mit Status, `user@host[:port]`, Tunnel-Pill (über
  `resolve_connection`), Suche im Verlauf (Enter weiter, Umschalt+Enter zurück), Schrift kleiner/größer, Optionen,
  Neu verbinden, Sitzung beenden; Fußzeile mit Größe (`Spalten×Zeilen`) und „verbunden seit hh:mm:ss“ /
  „verbinde …“ / „getrennt (Exit n)“. Bei *getrennt* steht im Terminal der Knopf *Neu verbinden*.
- **Status ehrlich:** *verbinde* vom Start des `ssh`-Prozesses bis zur ersten Ausgabe, *verbunden* solange der
  Prozess danach läuft, *getrennt* mit Exit-Code, sobald er endet. *Verbunden* heißt also „ssh läuft und hat
  geantwortet“, nicht „angemeldet“: Host-Key-Frage und Passwort-Abfrage beantwortet der Nutzer im Terminal, wie
  bisher im OS-Terminal (`known_hosts` von OpenSSH, keine eigene Prüfung).
- **Optionen** (Mockup-Panel, global für das Gerät): Schriftgröße 10–22 (Standard 13), Farbschema
  Cave/Kontrast/Hell (Standard Cave, Farben aus `terminal.jsx` `THEMES`), Cursor Block/Balken/Strich (Standard Block),
  Scrollback 1.000/10.000/100.000 (Standard 10.000), Kopieren beim Markieren (an), Rechtsklick fügt ein (an),
  Schließen bestätigen (an). Im Terminal (Panel *Optionen*, Schrift −/+) wird jede Änderung sofort gespeichert und
  gilt sofort für alle offenen Terminals. Dieselben Felder stehen in der neuen Sektion *Einstellungen → Terminal*
  (dort mit *Konsole für SSH*); sie folgt der Regel des Dialogs („Speichern nimmt alle“) und wirkt nach *Speichern*.
- **Schließen bestätigen:** Schließen eines Tabs mit laufender Sitzung fragt (ConfirmDialog), wenn die Option an ist;
  eine getrennte Sitzung schließt ohne Frage.
- **Tastatur im Terminal:** alle Tasten gehen an die Shell (auch Strg+K, Strg+L, Strg+C); Kopieren mit
  Strg+Umschalt+C, Einfügen mit Strg+Umschalt+V. Die Befehlspalette öffnet Strg+K nur außerhalb des Terminals.
- **Abmelden** und Neuladen des Fensters beenden alle Sitzungen dieses Fensters (keine unsichtbaren `ssh`-Prozesse).

**Nicht-Ziele** (YAGNI, jeweils eigene Zeile oder bewusst weggelassen):
- Abdocken in eigene Fenster, Andocken, Ringpuffer zum Wiederanhängen (R-1070); *In eigenem Fenster* im Split-Button
  kommt mit R-1070.
- Snippets, Broadcast (R-1071), SFTP (R-1072), Ansible-Live-Ausgabe (R-1073), eingebettetes RDP (R-1097/R-1098).
- Öffnen-Modus je Verbindung, Jump-Host, Port-Weiterleitung, Agent-Forwarding (R-1066).
- Aus dem Mockup, nicht in der Roadmap-Zeile: Zeichensatz ISO-8859-1, Keepalive-Schalter, strikte Host-Key-Prüfung
  als Schalter, Glocke als Benachrichtigung, Schriftwahl, *Alles kopieren*, *Leeren*, SSH-Version/Cipher in der
  Fußzeile (die App kennt sie nicht, R-1062: „Only what the app knows“).
- Klickbare Links in der Ausgabe (OSC 8, Web-Links-Addon): Ausgabe eines entfernten Hosts löst keine Navigation aus.
- Rückfrage beim Schließen des App-Fensters mit offenen Sitzungen (Folge-Zeile, `neu`).
- WebGL-Renderer: der DOM-Renderer reicht und hält den Text für den Live-E2E lesbar.
- Eigene SSH-Implementierung (russh o. ä.): Kevin 2026-11-02 hat System-OpenSSH entschieden.

## Betroffene Komponenten & Dateien

Nur der Desktop-Client; Server, Web, Agent, Monitoring und Gateway bleiben unberührt.

| Bereich | Datei | Änderung |
|---|---|---|
| Rust | `apps/desktop/src-tauri/Cargo.toml`, `Cargo.lock` | neue Crate `portable-pty` 0.9 |
| Rust | `apps/desktop/src-tauri/src/pty.rs` (neu) | Sitzungs-Registry, Spawn in Pseudo-Konsole, Lese-/Warte-Thread, Schreiben, Größe, Schließen |
| Rust | `apps/desktop/src-tauri/src/commands.rs` | Commands `terminal_open_ssh`, `terminal_write`, `terminal_resize`, `terminal_close`, `terminal_close_all`; Prüfung wie `open_connection` (`commands.rs:383`, `reject_foreign_port` `:370`) |
| Rust | `apps/desktop/src-tauri/src/main.rs` | `mod pty`, `.manage(PtyRegistry)` (`main.rs:127`), Commands im `generate_handler!` (`main.rs:220`) |
| Rust | `apps/desktop/src-tauri/src/connection/ssh.rs` | `build_ssh_args` (`ssh.rs:21`) für das PTY nutzbar (`pub(crate)`), argv ohne Shell |
| Rust | `apps/desktop/src-tauri/src/models.rs` | Ereignis `TerminalExit`; `SshConsole`, `TerminalPrefs`, `TerminalTheme`, `TerminalCursor`; Felder in `Settings` (`models.rs:91`) |
| Rust | `apps/desktop/src-tauri/src/storage.rs` | `Prefs` (`storage.rs:533`), `settings_of` (`:365`), `From<&Settings>`, `merged` (`:568`) um die neuen Felder |
| UI | `apps/desktop/ui/package.json`, `package-lock.json` | `@xterm/xterm` 6, `@xterm/addon-fit`, `@xterm/addon-search` |
| UI | `ui/src/lib/bridge/index.ts`, `bridge/types.ts` (`types.ts:40` `Settings`) | Bridge-Funktionen und Typen |
| UI | `ui/src/lib/models/settings.ts` (`getSettingsDefaults` `:15`) | Standardwerte, Grenzen der Terminal-Optionen |
| UI | `ui/src/lib/stores/terminals.ts` (neu) | Sitzungen, aktiver Tab, Status, Ausgabe-Puffer bis das Terminal hängt |
| UI | `ui/src/lib/stores/connectFlow.ts` (`initiateConnect` `:230`, `performConnect` `:270`) | Verzweigung eingebettet/extern für SSH, Modus je Start |
| UI | `ui/src/components/terminal/` (neu): `SshTerminal.svelte`, `TerminalOptions.svelte`, `SessionTabs.svelte`, `ConnectButton.svelte`; `ui/src/lib/terminal/themes.ts` (neu) | Terminal, Optionen, Tab-Leiste, Split-Button, Farbschemata |
| UI | `ui/src/components/AppShell.svelte` (`onWindowKeydown` `:170`, `content-main` `:403`), `StatusFooter.svelte`, `components/connections/ConnectionInspector.svelte` | Tab-Leiste, Sitzungs-Panes, Strg+K-Ausnahme, Sitzungszahl, Split-Button |
| UI | `ui/src/components/settings/SettingsDialog.svelte`, `settings/TerminalSection.svelte` (neu) | Sektion *Terminal* |
| UI | `ui/src/lib/i18n/dictionaries.ts` | Texte DE/EN |
| E2E | `apps/desktop/e2e/test/specs/ssh-connect.live.js`, `e2e/test/lib/live.js`, `scripts/tests/desktop_e2e_connect.sh` | Journey eingebettet (Tab, Host-Key, Passwort, Befehl, Ausgabe) und OS-Terminal über das Menü |
| Doku | `README.md`, `docs/admin/index.html` + `docs/en/admin/index.html`, `docs/developer/desktop.html` + `docs/en/developer/desktop.html`, `THIRD_PARTY_LICENSES.md`, `changelog.d/arch-ssh-terminal.md` | siehe Doku-Impact |

## Datenmodell / API / Migrationen

Keine Alembic-Migration, kein Server-Vertrag. Neu ist ein Tauri-IPC-Vertrag (Rust ↔ `bridge/`), geprüft von
`types.parity.test.ts`.

**Commands** (nur im Workspace-Prozess: `reject_foreign_port` braucht `workspace::current()`, der Launcher lehnt ab):
- `terminal_open_ssh(connection: Connection, cols: u16, rows: u16, output: Channel<InvokeResponseBody>) -> u64`
  — `connection` ist die schon aufgelöste (`resolve_connection`, wie `open_connection`); prüft `reject_foreign_port`
  mit den Bindings des eigenen frpc, sucht `ssh` als absoluten Pfad nur in `PATH` (`terminal::which`, Ergebnis muss
  absolut sein), baut argv aus `build_ssh_args` (kein `bash -c`, keine Shell), setzt `TERM=xterm-256color`, startet in
  einer Pseudo-Konsole der Größe `cols×rows` und gibt die Sitzungs-Id zurück.
- `terminal_write(id: u64, data: Vec<u8>)` — Tastatureingabe (xterm `onData` als UTF-8, `onBinary` bytegenau).
- `terminal_resize(id: u64, cols: u16, rows: u16)`, `terminal_close(id: u64)` (beendet den Prozess),
  `terminal_close_all()` (beim Start der Oberfläche und vor dem Neuladen beim Abmelden).
- Eingaben und Ausgaben werden nie geloggt (Passwörter laufen durch `terminal_write`).

**Kanal-Protokoll** (`output`, ein Kanal je Sitzung, Reihenfolge garantiert):
- Ausgabe: `InvokeResponseBody::Raw(bytes)` → in JS ein `ArrayBuffer`, an `term.write(new Uint8Array(…))`.
- Ende: genau eine letzte Nachricht `InvokeResponseBody::Json` mit `TerminalExit { exitCode: Option<u32> }` →
  in JS ein Objekt; danach sendet die Sitzung nichts mehr und verlässt die Registry.
- Schlägt `send` fehl (Webview weg), beendet die Sitzung den Prozess.

**Lebenszyklus im Backend** (`pty.rs`): `openpty` → `spawn_command` → Slave sofort droppen (sonst bleibt unter Unix
die Slave-Seite offen und der Leser bekommt nie EOF) → Lese-Thread (blockierendes `read`, je Block ein `send`) und
Warte-Thread (`child.wait()`, danach Master freigeben, damit unter Windows die ConPTY schließt und der Leser EOF
bekommt) → nach EOF und Exit sendet der Lese-Thread `TerminalExit`. `terminal_close` ruft den `ChildKiller`. Das
Modul bleibt `#![forbid(unsafe_code)]`; die Registry ist generisch (Programm + argv), damit R-1073 und R-1070 darauf
aufsetzen.

**Einstellungen** (global je Gerät in `prefs.json`, wie die RDP-Optionen; `#[serde(default)]` je neuem Feld, damit ein
`prefs.json` von 0.46 lädt; ältere Versionen ignorieren unbekannte Felder):
- `sshConsole: "embedded" | "external"` (`SshConsole`).
- `terminal: { fontSize, theme: "cave"|"contrast"|"light", cursor: "block"|"bar"|"underline", scrollback,
  copyOnSelect, rightClickPaste, confirmClose }` (`TerminalPrefs`). Die Oberfläche begrenzt `fontSize` auf 10–22 und
  `scrollback` auf die drei Stufen, auch für ein von Hand geändertes `prefs.json`. `merged` nimmt `terminal` als
  Ganzes (zwei Prozesse, die gleichzeitig verschiedene Terminal-Optionen ändern: der letzte gewinnt).

## Externe Integrationen

- **Tauri v2 Channels** (tauri 2.12.5): <https://v2.tauri.app/develop/calling-frontend/#channels>,
  <https://docs.rs/tauri/2/tauri/ipc/struct.Channel.html>, `InvokeResponseBody`
  <https://docs.rs/tauri/2/tauri/ipc/enum.InvokeResponseBody.html>. Belegt: Reihenfolge je Kanal, `Raw` kommt als
  `ArrayBuffer`. Nicht dokumentiert: Gegendruck, `send` nach Neuladen des Webviews, dass `Json` als geparstes Objekt
  ankommt (aus dem Quelltext von `@tauri-apps/api` abgeleitet) — der Live-E2E belegt den Weg.
- **portable-pty 0.9.0** (MIT, wezterm): <https://docs.rs/portable-pty/0.9.0/portable_pty/>. `native_pty_system`,
  `openpty(PtySize)`, `spawn_command(CommandBuilder)`, `try_clone_reader`, `take_writer` (einmal), `resize`,
  `clone_killer`; Windows über ConPTY. Nicht dokumentiert: Mindest-Windows-Version, EOF-Verhalten unter Windows —
  abgesichert durch einen PTY-Rundlauf-Test, der im CI-Job `rust-windows` nativ läuft.
- **xterm.js 6.0.0** (`@xterm/xterm`, MIT, ohne Abhängigkeiten), `@xterm/addon-fit` 0.11, `@xterm/addon-search`
  0.16: <https://xtermjs.org/docs/api/terminal/classes/terminal/>, Optionen
  <https://xtermjs.org/docs/api/terminal/interfaces/iterminaloptions/>. CSP der App
  (`tauri.conf.json:16`: `script-src 'self'`, `style-src 'self' 'unsafe-inline'`) reicht laut Aufbau (kein `eval`,
  Inline-Styles erlaubt); nicht in der xterm-Doku belegt, der Live-E2E zeigt es.
- **OpenSSH-Client** (`ssh`/`ssh.exe` im `PATH`): Host-Key-Frage, `known_hosts`, Passwort-Abfrage bleiben bei
  OpenSSH. Windows: der mitgelieferte OpenSSH-Client (ab Windows 10 1809) — nicht verifiziert.
- **Clipboard:** `navigator.clipboard.writeText` (schon in `CodeBlock.svelte`), `readText` für Rechtsklick-Einfügen;
  ob WebKitGTK/WebView2 `readText` ohne Rückfrage erlauben, ist nicht verifiziert. Scheitert es, zeigt das Terminal
  den Hinweis auf Strg+Umschalt+V (natives Einfügen, das xterm selbst verarbeitet).

## Trade-offs & Alternativen

- **PTY + System-OpenSSH** (gewählt, Kevin) statt eigener SSH-Implementierung: Nutzer behalten `~/.ssh/config`,
  Agent, Schlüssel, `known_hosts`; keine Krypto im App-Code. Preis: der Status kennt keine Anmeldung, nur den Prozess.
- **portable-pty** statt eigener `openpty`/ConPTY-Aufrufe: eine Abstraktion für Unix und Windows ohne `unsafe` im
  App-Code; reif (wezterm). Preis: eine Crate mit wenig Doku und letztem Release 2025-02. Alternative
  `pty-process` kann kein Windows.
- **Ein Kanal je Sitzung, Ende als letzte Nachricht** statt Tauri-Event für das Ende: Reihenfolge Ausgabe → Ende ist
  garantiert, das Ereignis geht nur an das aufrufende Webview. Alternative zwei Kanäle: kein Ordnungsversprechen.
- **Registry im Backend** statt Prozess je Webview-Aufruf ohne Gedächtnis: Voraussetzung für Abdocken (R-1070) und
  für Aufräumen nach Abmelden; Ringpuffer erst mit R-1070.
- **Optionen global** (`prefs.json`) statt je Sitzung: eine Stelle, gleiches Verhalten in allen Workspaces; die
  Mockup-Optionen im Terminal schreiben dieselben Werte.
- **DOM-Renderer** statt WebGL: weniger Code und GPU-Abhängigkeit unter WebKitGTK; Preis: langsamer bei sehr viel
  Ausgabe (hingenommen, messbar später).
- **Split-Button nur im Inspector**: eine sichtbare Stelle für die Abweichung je Start; alle anderen Wege nehmen die
  Einstellung, wie im Mockup (`ConnectMenu` neben *Verbinden*).

## Risiken & Rollback

- **Windows ungeprüft in der GUI:** ConPTY, `ssh.exe`, Clipboard und Tastatur laufen nur als `cargo test` in
  `rust-windows`; die Windows-GUI bleibt „nicht verifiziert“ (testing.md). Rückweg: Einstellung *OS-Terminal*.
- **Viel Ausgabe** (`cat` einer großen Datei, `yes`): ein `send` je Leseblock ohne Gegendruck kann das Webview
  bremsen; Leseblock 64 KiB, Messung im Live-E2E nicht vorgesehen. Folge-Zeile, wenn es auffällt.
- **Verwaiste `ssh`-Prozesse:** abgedeckt durch `terminal_close_all` beim Start der Oberfläche, Kill bei
  `send`-Fehler, Pseudo-Konsole schließt mit dem Prozess (Unix: SIGHUP an `ssh`). App-Absturz unter Windows:
  nicht verifiziert.
- **Vertrag** `Settings`/`prefs.json` (Risikopfad `models.rs`, `bridge/types.ts`): neue Felder mit Default, Test mit
  altem `prefs.json`; `security` prüft die Tasks mit Risikopfad und den Prozess-Start.
- **Live-E2E auf dem VM-Pfad neu:** die PR-CI fährt keine GUI; der Sammellauf (`linux-full`) oder ein gezielter
  `desktop_e2e_connect`-Lauf vor dem Merge zeigt die Journey.
- **Rollback:** Revert des Merge-Commits; `prefs.json` mit den neuen Feldern bleibt für ältere Versionen lesbar
  (unbekannte Felder ignoriert). Für Nutzer: Einstellung *OS-Terminal* stellt das alte Verhalten her.

## Doku-Impact

DE+EN: Bedienung der Verbindungen (Konsole, Split-Button, Tabs, Optionen, Tastatur) in `docs/admin/index.html` und
`docs/en/admin/index.html`; Architektur (Modul `pty.rs`, Commands, Kanal-Protokoll, Einstellungen, sechste
Settings-Sektion, Verbindungs-Ablauf) in `docs/developer/desktop.html` und `docs/en/developer/desktop.html`;
`README.md` (Plattform-Verhalten SSH); `THIRD_PARTY_LICENSES.md` (portable-pty und neue Crates im Graphen, xterm-Pakete);
`changelog.d/arch-ssh-terminal.md` (Added).

## Offene Fragen

1. **Standardwert der Konsole** (Kevins Bereich, Roadmap: „Standardwert im Plan (Kevin)“) — Ledger T3 `[?]`.
   Empfehlung: **AdminHelper-Terminal**: das Mockup führt *Eingebettet (Tab)* als Standard, es braucht keinen
   Terminal-Emulator und zeigt Status und Neu verbinden; Preis: nach dem Update öffnet ein Doppelklick einen Tab statt
   des OS-Terminals (CHANGELOG nennt es, die Einstellung stellt es zurück). Alternative **OS-Terminal**: keine
   Überraschung, das neue Terminal nur über Split-Button oder Einstellung. Bis zur Antwort baut der Branch mit
   *OS-Terminal* (heutiges Verhalten); T3 setzt nur den Wert.
