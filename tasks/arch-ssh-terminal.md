<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-ssh-terminal — Task-Ledger
Status: aktiv · Branch: feature/arch-ssh-terminal · Review: pro Task
Spec: docs/features/arch-ssh-terminal.md (Roadmap R-1069)
Heavy: linux-full — neue Desktop-Journey (`ssh-connect.live.js` über `scripts/tests/desktop_e2e_connect.sh`), Sammellauf. Weil die PR-CI keine GUI fährt und der Kanal-Weg (Raw/Json, CSP) erst in der echten Webview belegt ist, läuft vor dem Merge zusätzlich `desktop_e2e_connect` auf der Lane-VM (`/test`). Kein `scenario` (kein Tunnel-Datenpfad neu, `resolve_connection` unverändert), kein `windows` (Pool ohne Windows-Vorlage; ConPTY über `rust-windows`).
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `reviewer` je Task (ein Prüfer für den Zug, fortgesetzt); `security` dazu bei T1 (Prozessstart, Risikopfade
`models.rs`, `bridge/types.ts`) und T2 (Risikopfade `models.rs`, `bridge/types.ts`, `prefs.json`-Vertrag).
Reihenfolge: T1 → T10 → T4 → T5 → T6 → T7 → T8; T2 vor T4 (der Zweig liest `sshConsole`); T3 nach Kevins Antwort, jederzeit
nach T2; T9 zuletzt (vorher `origin/main` hineinmergen: `feature/kern-laufzeit-2` ändert `THIRD_PARTY_LICENSES.md`,
`feature/kern-pg-1` `README.md` und `docs/admin/index.html`, jeweils andere Abschnitte).

## Tasks

### T1 — PTY-Backend, Terminal-Commands und Bridge (R-1069)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/Cargo.toml, apps/desktop/src-tauri/Cargo.lock, apps/desktop/src-tauri/src/pty.rs (neu, SPDX), apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/connection/ssh.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/types.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, apps/desktop/ui/src/lib/bridge/invoke.test.ts
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @e78f3fa1 2026-11-05T09:34:18+01:00
Review: approve (.ah-out/review/arch-ssh-terminal/T1.verdict.json)
Umfang: zwölf Dateien, weil der IPC-Vertrag (Command, Registrierung, Bridge, Typ, Command-Tabelle der Entwickler-Doku)
nur zusammen grün wird (`types.parity.test.ts`, `ipc.inventory.test.ts`).
Änderung:
- `Cargo.toml`: `portable-pty = "0.9"`; neuen Crate-Graphen auf Advisories prüfen (`cargo audit`, falls lokal da,
  sonst im Commit-Body nennen, dass `audit.yml` es wöchentlich prüft).
- `pty.rs` (`#![forbid(unsafe_code)]`): `PtyRegistry` (managed State, `Mutex<HashMap<u64, …>>`, Zähler-Id), generisch
  über Programm + argv + Umgebung + cwd. `open` → `openpty(PtySize)` → `spawn_command` → Slave droppen →
  Lese-Thread (Block bis 64 KiB, je Block ein `send`) und Warte-Thread (`child.wait()`, dann Master freigeben).
  Nach EOF und Exit genau eine letzte Nachricht `TerminalExit` (Json), danach raus aus der Registry. `write`,
  `resize`, `close` (ChildKiller), `close_all`. Ein `send`-Fehler beendet die Sitzung. Kein Logging von Ein- oder
  Ausgabe. Die Senke ist ein Trait/Closure, damit die Tests ohne Tauri-Kanal laufen.
- `commands.rs`: `terminal_open_ssh(connection, cols, rows, output: Channel<InvokeResponseBody>) -> u64` mit
  Bindings und `reject_foreign_port` wie `open_connection` (`commands.rs:383`, `:370`); `ssh` nur als absoluter
  Pfad aus `terminal::which`; argv aus `build_ssh_args` (`connection/ssh.rs:21`, wird `pub(crate)`), kein Shell-Aufruf;
  `TERM=xterm-256color`, cwd = Home. Dazu `terminal_write(id, data: Vec<u8>)`, `terminal_resize`, `terminal_close`,
  `terminal_close_all`. Nicht-SSH-Verbindungen lehnt `terminal_open_ssh` ab.
- `main.rs`: `mod pty`, `.manage(pty::PtyRegistry::default())` (`main.rs:127`), Commands in `generate_handler!`
  (`main.rs:220`).
- `models.rs`: `TerminalExit { exit_code: Option<u32> }` (camelCase). `bridge/types.ts` gleichzieht
  (`types.parity.test.ts`); `bridge/index.ts`: `terminalOpenSsh(connection, cols, rows, onMessage)` erzeugt den
  `Channel` aus `@tauri-apps/api/core` und reicht `ArrayBuffer` bzw. `TerminalExit` an `onMessage`; `terminalWrite`,
  `terminalResize`, `terminalClose`, `terminalCloseAll`.
- Tests (Rust): PTY-Rundlauf mit `sh -c 'printf ah-pty-ok; exit 3'` (Windows `cmd /c "echo ah-pty-ok & exit /b 3"`):
  Ausgabe kommt vor dem Ende, Exit-Code 3, genau ein Ende; Schreiben (`read x; printf got:%s "$x"`); `close` beendet
  `sleep 30` mit Ende; `close_all`; argv für `terminal_open_ssh` ohne Shell und mit absolutem `ssh`; Ablehnung von
  RDP/Web. Laufen nativ auch im CI-Job `rust-windows` (ConPTY-Beleg).
- Tests (UI): `invoke.test.ts`/`ipc.inventory.test.ts` sehen die neuen Commands (Inventar zählt die Tabelle der
  Entwickler-Doku mit).
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Command-Tabelle, vom Inventar-Test verlangt); Prosa → T9

### T2 — Einstellungen: Konsole für SSH und Terminal-Optionen (R-1069)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/lib/models/settings.test.ts, apps/desktop/ui/src/components/Login.workspace.test.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts, apps/desktop/ui/src/components/StatusFooter.test.ts, apps/desktop/ui/src/components/SettingsModal.nav.test.ts, apps/desktop/ui/src/components/SettingsModal.seed.test.ts, apps/desktop/ui/src/components/SettingsModal.workspace.test.ts, apps/desktop/ui/src/lib/stores/session.test.ts, apps/desktop/src-tauri/src/migration.rs
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @bdeb25b8 2026-11-05T09:54:44+01:00
Review: approve (.ah-out/review/arch-ssh-terminal/T2.verdict.json)
Änderung:
- `models.rs`: `SshConsole` (`embedded` | `external`, `#[default]` vorerst `external`), `TerminalTheme`
  (`cave`|`contrast`|`light`), `TerminalCursor` (`block`|`bar`|`underline`), `TerminalPrefs { font_size: u8 = 13,
  theme, cursor, scrollback: u32 = 10000, copy_on_select = true, right_click_paste = true, confirm_close = true }`;
  Felder `ssh_console` und `terminal` in `Settings` (`models.rs:91`) mit `#[serde(default)]`.
- `storage.rs`: dieselben Felder in `Prefs` (`storage.rs:533`, `#[serde(default)]`), `settings_of` (`:365`),
  `From<&Settings> for Prefs`, `merged` (`:568`; `terminal` als Ganzes).
- `types.ts` und `models/settings.ts` (`getSettingsDefaults` `:15`): Typen, Standardwerte, `clampTerminalPrefs`
  (Schrift 10–22, Scrollback auf 1.000/10.000/100.000).
- Tests: altes `prefs.json` ohne die Felder lädt mit Standardwerten; Rundlauf speichern/laden; `merged` übernimmt
  eine Terminal-Änderung des eigenen Prozesses und behält die eines zweiten; Clamp-Grenzen in TS.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T9
Abhängt von: T1

### T3 — Standardwert der Konsole für SSH (R-1069)  [?] (Standardwert der Konsole für SSH: AdminHelper-Terminal oder OS-Terminal?)
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/lib/models/settings.test.ts, apps/desktop/src-tauri/src/storage.rs
Änderung: `#[default]` von `SshConsole` und `getSettingsDefaults().sshConsole` auf Kevins Wert; die Tests aus T2, die
den Standard prüfen, auf den Wert ziehen. Bleibt es bei `external`, wird die Task `[~]` (nichts zu ändern).
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: → T9
Abhängt von: T2

### T4 — Sitzungs-Store und Verbindungs-Zweig (R-1069)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts (neu, SPDX), apps/desktop/ui/src/lib/stores/terminals.test.ts (neu, SPDX), apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, apps/desktop/ui/src/lib/stores/settings.ts, apps/desktop/ui/src/lib/stores/settings.test.ts, apps/desktop/ui/src/main.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @4e394e72 2026-11-05T10:31:03+01:00
Review: approve (.ah-out/review/arch-ssh-terminal/T4.verdict.json)
Änderung:
- `terminals.ts`: Sitzungen (key, Verbindung, aufgelöste Verbindung, Status `connecting`|`connected`|`disconnected`,
  Exit-Code, `connectedAt`, Backend-Id), aktiver Tab (`page` oder key), Ausgabe-Puffer bis ein Terminal sich anhängt
  (`attach(key, sink)`), `open`, `reconnect` (neu auflösen, neue Backend-Id, derselbe Tab), `close`, `closeAll`.
  Status: erste Ausgabe → `connected`, `TerminalExit` → `disconnected`, ein Fehler beim Öffnen → `disconnected` mit
  Meldung in der Statusleiste.
- `connectFlow.ts`: `initiateConnect(connection, keepEditorOpen, mode?)` (`connectFlow.ts:230`): SSH nach
  `mode ?? settings.sshConsole`; `embedded` öffnet einen Tab statt `open_connection`, `external` wie bisher. Die
  Prüfung und Auflösung davor bleibt dieselbe.
- Start der Oberfläche ruft `terminalCloseAll` (Waisen eines früheren Ladens); `logoutAndReload` (`stores/settings.ts`)
  ruft es vor dem Neuladen. Den Einstiegspunkt beim Bau festlegen (`App.svelte` oder `main.ts`, Liste per `set-files`).
- Tests: Zweig je Modus und Einstellung, Puffer bis zum Attach, Status-Übergänge, Neu verbinden, Schließen, Fehler.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T9
Abhängt von: T1, T2

### T5 — Terminal-Komponente, Farbschemata und Optionen (R-1069)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, apps/desktop/ui/src/lib/terminal/themes.ts (neu, SPDX), apps/desktop/ui/src/components/terminal/SshTerminal.svelte (neu, SPDX), apps/desktop/ui/src/components/terminal/TerminalOptions.svelte (neu, SPDX), apps/desktop/ui/src/components/terminal/SshTerminal.test.ts (neu, SPDX), apps/desktop/ui/src/lib/stores/terminalPrefs.ts (neu, SPDX), apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung:
- Pakete `@xterm/xterm` 6, `@xterm/addon-fit`, `@xterm/addon-search` (exakte Versionen im Lockfile).
- `themes.ts`: Cave/Kontrast/Hell aus `terminal.jsx` `THEMES` auf `ITheme` (16 ANSI-Farben, Auswahl, Cursor).
- `SshTerminal.svelte`: xterm (DOM-Renderer, `linkHandler` ohne Aktivierung, Schrift `--font-mono` nach `document.fonts.ready`),
  fit bei Größenänderung → `terminalResize`; Eingabe `onData`/`onBinary` → `terminalWrite`; Kopfzeile (Status-Punkt,
  `user@host[:port]`, Tunnel-Pill, Suche mit Enter/Umschalt+Enter, Schrift −/+, Optionen, Neu verbinden, Beenden);
  Fußzeile (Größe, verbunden seit / verbinde / getrennt mit Exit); bei getrennt der Knopf *Neu verbinden*; Kopieren
  beim Markieren, Rechtsklick fügt ein (`clipboard.readText`, sonst Hinweis auf Strg+Umschalt+V), Strg+Umschalt+C/V.
- `TerminalOptions.svelte`: die Optionen aus der Spec als Formular mit `bind:`-Wert; `terminalPrefs.ts` speichert
  aus dem Terminal sofort (`bridge.saveSettings` mit den aktuellen Settings + neuem `terminal`, dann `refreshSettings`).
- i18n DE/EN.
- Tests (vitest, `@xterm/xterm` per `vi.mock`): Eingabe geht an `terminalWrite`, Puffer/Ausgabe an `write`, Optionen
  setzen `fontSize`/`theme`/`cursorStyle`/`scrollback`, Kopieren beim Markieren an/aus, Rechtsklick an/aus,
  Suche vor/zurück, getrennt zeigt *Neu verbinden*.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T9
Abhängt von: T4

### T6 — Tab-Leiste, Sitzungs-Panes und Tastatur (R-1069)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/SessionTabs.svelte (neu, SPDX), apps/desktop/ui/src/components/terminal/SessionTabs.test.ts (neu, SPDX), apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.sessions.test.ts (neu, SPDX), apps/desktop/ui/src/components/StatusFooter.svelte, apps/desktop/ui/src/components/StatusFooter.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung:
- `SessionTabs.svelte` nur bei ≥ 1 Sitzung: Seiten-Tab, je Sitzung Icon, Name, Status-Punkt, Schließen (ConfirmDialog,
  wenn `confirmClose` an und nicht getrennt); Tastatur wie die Tab-Leisten der App (Pfeiltasten).
- `AppShell.svelte`: Tab-Leiste unter dem Header, Sitzungen gemountet und nur die aktive sichtbar (`content-main`
  `:403`); Sidebar-Navigation holt den Seiten-Tab nach vorn; Header zeigt bei aktiver Sitzung Name und `SSH · host`;
  `onWindowKeydown` (`:170`) lässt Strg/⌘+K aus einem `.xterm` an die Shell.
- `StatusFooter.svelte`: „N Sitzung(en)“, nur bei ≥ 1.
- Tests: Leiste erscheint/verschwindet, Wechsel Seite/Sitzung, inaktive bleiben gemountet, Schließen mit und ohne
  Rückfrage, Strg+K im Terminal öffnet die Palette nicht, außerhalb schon; Zähler im Footer.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T9
Abhängt von: T5

### T7 — Split-Button im Inspector und Sektion Terminal in den Einstellungen (R-1069)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/terminal/ConnectButton.svelte (neu, SPDX), apps/desktop/ui/src/components/terminal/ConnectButton.test.ts (neu, SPDX), apps/desktop/ui/src/components/connections/ConnectionInspector.svelte, apps/desktop/ui/src/components/settings/TerminalSection.svelte (neu, SPDX), apps/desktop/ui/src/components/settings/SettingsDialog.svelte, apps/desktop/ui/src/components/SettingsModal.nav.test.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung:
- `ConnectButton.svelte` (auf `ui/Menu.svelte`): bei SSH Hauptknopf *Verbinden* (Einstellung) und Pfeil mit
  *Im AdminHelper-Terminal* / *Im OS-Terminal* (`initiateConnect(c, …, mode)`); sonst der einfache Knopf. Ersetzt
  den Knopf in `ConnectionInspector.svelte:89`.
- `TerminalSection.svelte` in `SettingsDialog.svelte`: *Konsole für SSH* und `TerminalOptions` (`data-scope="device"`),
  gespeichert mit *Speichern* wie die übrigen Sektionen.
- Tests: Menü startet mit dem gewählten Modus, Hauptknopf mit der Einstellung, RDP/Web ohne Menü; Sektion in der
  Navigation, Speichern trägt `sshConsole` und `terminal`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: → T9
Abhängt von: T5

### T8 — Live-E2E: SSH im eingebetteten Terminal und im OS-Terminal (R-1069)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/ssh-connect.live.js, apps/desktop/e2e/test/lib/live.js, scripts/tests/desktop_e2e_connect.sh
Änderung:
- `ssh-connect.live.js`: über das Split-Menü *Im AdminHelper-Terminal*: Tab erscheint, Host-Key mit `yes`, Passwort
  `e2e`, `echo AH_E2E_$((6*7))` ergibt `AH_E2E_42` in `.xterm-rows`, Status *verbunden*; `exit` → *getrennt*,
  *Neu verbinden* verbindet im selben Tab; Schließen einer laufenden Sitzung fragt. Eigener `it` für den Weg
  *Im OS-Terminal* (heutiger Ablauf, sshd-Log wie bisher).
- `desktop_e2e_connect.sh`: alter Host-Key von `[127.0.0.1]:2222` vor dem Lauf aus `known_hosts` entfernen, wenn die
  Datei existiert (`ssh-keygen -R`); Kopfkommentar (`EXTERNAL process`) auf beide Wege ziehen; Prüfung im sshd-Log
  für beide Anmeldungen.
Verify: bash scripts/dev/verify.sh desktop-e2e scripts --strict
Doku: → T9
Abhängt von: T6, T7

### T10 — Windows: eine Sitzung ohne Zuhörer beantwortet die Cursor-Abfrage der Pseudo-Konsole (R-1069)  [x]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/pty.rs
Evidenz: run.sh[quick] desktop: 3 passed, 0 failed, 15 skipped @36f6d8c1 2026-11-05T10:09:48+01:00
Review: approve (.ah-out/review/arch-ssh-terminal/T10.verdict.json)
Beweis: feature/arch-ssh-terminal@454a7b28, `gh workflow run ci.yml --ref feature/arch-ssh-terminal` (Lauf 41995544339), Job „Desktop-Backend (cargo test, Windows)“: `pty::tests::a_sink_nobody_listens_to_ends_the_program ... FAILED`, `src\pty.rs:327:13: the session stays in the registry` (erwartet: die Sitzung ist nach dem Kill binnen 20 s weg); die übrigen sieben PTY-Tests dort grün. Auf Linux nicht reproduzierbar: die Abfrage stellt nur ConPTY.
HEAD: 454a7b28
Änderung: portable-pty erzeugt die ConPTY mit `PSEUDOCONSOLE_INHERIT_CURSOR` (`portable-pty-0.9.0/src/win/psuedocon.rs:87`); laut Microsoft („Creating a Pseudoconsole session“, Abschnitt „Ending the Pseudoconsole Session“) kann das Schließen ohne Antwort auf die Cursor-Abfrage verklemmen. Hört niemand mehr zu, beantwortet der Lese-Thread unter Windows jede Cursor-Abfrage (`ESC[6n`) selbst mit `ESC[1;1R`; `CURSOR_QUERY`, `CURSOR_ANSWER` und `contains` ziehen aus dem Testmodul auf Modulebene (`cfg(any(windows, test))`). Der rote Test selbst bleibt unverändert und beweist den Fix auf `rust-windows` (`gh workflow run ci.yml --ref feature/arch-ssh-terminal` nach dem Commit, Ergebnis unter `## Entscheidungen`).
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: keine (internes Verhalten der PTY-Sitzung; Commands und ihre Tabelle bleiben)
Abhängt von: T1

### T9 — Doku DE+EN, Lizenzen, CHANGELOG (R-1069)  [ ]
Komponente: desktop · Dateien: README.md, docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, THIRD_PARTY_LICENSES.md, changelog.d/arch-ssh-terminal.md
Änderung: `README.md` „Platform behavior“ SSH (Zeile 26); Admin-Handbuch DE+EN (Verbindungen: Konsole, Split-Button,
Tabs, Optionen, Tastatur, Status-Bedeutung); Entwickler-Doku DE+EN (Modulbaum `pty.rs`, Kanal-Protokoll, Lebenszyklus,
neue Settings-Felder global, sechste Sektion im Einstellungsdialog, `terminal_open_ssh` in *Fremde Ports* und im
Connect-Flow); `THIRD_PARTY_LICENSES.md` (portable-pty direkt, Crate-Graph neu, xterm-Pakete in der UI-Tabelle);
`changelog.d/arch-ssh-terminal.md` (`### Added`, umlautfrei, mit dem Standardwert aus T3).
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: README · docs/admin DE+EN · docs/developer/desktop DE+EN · THIRD_PARTY_LICENSES.md · changelog.d/arch-ssh-terminal.md
Task-Review: am Ende
Abhängt von: T3, T8

## Entscheidungen
- 2026-11-05 T1: Der Warte-Thread wartet blockierend (`child.wait()`) und nimmt den `ChildKiller` gleich danach weg; `close` nach dem Ende signalisiert nichts mehr — so trifft ein Kill keine Prozess-Id, die das System schon weitergegeben hat (Restfenster zwischen Wait und Wegnahme: Mikrosekunden, Pids werden fortlaufend vergeben).
- 2026-11-05 T1: Eine Senke, die `false` liefert (Kanal weg), beendet das Programm, der Leser liest aber bis EOF weiter — sonst hielte ein voller Pty-Puffer das Programm auf und der Warte-Thread käme nie zum Ende.
- 2026-11-05 T1: `ssh` nur als absoluter Pfad aus `terminal::which`; ein relativer Treffer gilt als nicht gefunden — sonst entschiede das Arbeitsverzeichnis der App, welches Programm läuft (`terminal.rs` bleibt unverändert).
- 2026-11-05 T1: `close_all` beim `RunEvent::Exit` in Rust und `terminalCloseAll` beim Start der UI (T4) — Tauri-`send` scheitert nach einem Webview-Reload nicht, die Programme hingen sonst ohne Leser an einem toten Kanal.
- 2026-11-05 T1: `terminal_write` läuft über `blocking()`; zwei gleichzeitige Invokes könnten die Reihenfolge tauschen, darum serialisiert der Store (T4) die Eingabe je Session (nächster Write erst nach dem letzten).
- 2026-11-05 T2: `sshConsole` und `terminal` sind im TS-Typ `Settings` Pflicht (Rust sendet beide immer); darum ziehen sieben Test-Fixtures, die ein ganzes `Settings` bauen, die Felder als Literal nach (drei liegen in `vi.hoisted`, ein Import ginge dort nicht), und die beiden Migrationstests in `migration.rs` erwarten die Standardwerte in der migrierten `prefs.json` — T2 trägt damit dreizehn Dateien.
- 2026-11-05 T2: `TerminalPrefs` hat `#[serde(default)]` auf Struct-Ebene: ein von Hand gekürztes `terminal`-Objekt lädt mit Standardwerten für die fehlenden Optionen; ein ungültiger Wert (etwa `fontSize: 300` über `u8`) scheitert wie jedes andere ungültige Feld von `prefs.json`. `clampTerminalPrefs` nimmt beim Scrollback die nächste Stufe.
- 2026-11-05 T4: Schreiben, Größe und Tab-Wechsel laufen über den Store (`writeTerminal`, `resizeTerminal`, `showTab`), die Backend-Id bleibt in ihm; jeder Start zählt (`attempt`), Nachrichten eines ersetzten oder geschlossenen Programms gehen ins Leere, ein Start, dessen Tab inzwischen zu ist, beendet sein Programm. Die Größe merkt sich der Store, ein Neu-Verbinden startet mit ihr.
- 2026-11-05 T4: Das Aufräumen beim Start (`terminalCloseAll`) steht in `main.ts`, nicht in `App.svelte`: mehrere Tests mounten `App` über Bridge-Mocks ohne Terminal-Befehle; `App.svelte` ist aus `Dateien:` gestrichen.
- 2026-11-05 T4 (Review): Eingaben, bevor `terminal_open_ssh` die Id meldet, wartet der Store je Start in `input` und schickt sie mit der Id in Tipp-Reihenfolge (die Cursor-Abfrage der Windows-Pseudo-Konsole kommt in diesem Fenster); ein neuer Start oder ein gescheiterter verwirft sie, ein Write geht nur an das Programm, für das er getippt wurde.
- 2026-11-05 T4: Ein eingebetteter Start zeigt keine Statusmeldung (der Tab zeigt den Verlauf), ein gescheiterter Start markiert die Verbindung nicht als benutzt und lässt den Editor offen; ohne geladene Einstellungen gilt `external`.
- 2026-11-05 T10: Beleg Windows: `ci.yml` per `workflow_dispatch` auf 4e394e72 (Lauf 42000125979), Job „Desktop-Backend (cargo test, Windows)“ im zweiten Versuch grün, `pty::tests::a_sink_nobody_listens_to_ends_the_program ... ok`, 674 passed, 0 failed; der erste Versuch scheiterte vor den Tests am frpc-Download (HTTP 504), nur dieser Job lief erneut.
