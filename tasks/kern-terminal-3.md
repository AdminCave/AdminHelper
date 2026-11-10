# Desktop-Terminal: Dateien, Befehle, Einfügen, Sitzungsverlauf — Task-Ledger
Status: aktiv · Branch: feature/kern-terminal-3 · Review: pro Task
Spec: docs/features/kern-terminal-3.md (Roadmap R-1170, R-1171, R-1174, R-1155, R-1165, R-1166, R-1144, R-1175, R-1159)
Heavy: linux-full — Desktop-Journeys (eingebettetes Terminal, Dateien-Panel); Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1170, R-1171: Teildatei des Downloads exklusiv anlegen, Dateinamen-Vorschlag bereinigen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs, apps/desktop/src-tauri/src/commands.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @d181e95ac 2026-11-10T02:03:03+01:00
Review: approve (.ah-out/review/kern-terminal-3/T1.verdict.json)
Änderung:
- `download` legt die Teildatei mit `OpenOptions::create_new` an. Liegt eine alte Teildatei dort, wird sie entfernt
  und einmal neu exklusiv angelegt; scheitert auch das, bricht der Download mit Fehler ab.
- Neue Funktion `sftp::suggested_name`: ersetzt `\`, `:`, `/` und Steuerzeichen durch `_`, `.`/`..`/leer →
  `download`. `sftp_download` schlägt diesen Namen vor; Fortschritt und Meldungen nennen ihn ebenso.
- Tests: vorhandene Teildatei, eine Teildatei als Symlink (Ziel bleibt unverändert), Namensfälle.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp::
Doku: → T7

### T2 — R-1155, R-1165, R-1166: PATH-Suche nur absolut, Fensterprüfung, `check` als bool  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/terminal.rs, apps/desktop/src-tauri/src/commands.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @086bcb708 2026-11-10T02:07:03+01:00
Review: approve (.ah-out/review/kern-terminal-3/T2.verdict.json)
Änderung:
- `terminal::which` überspringt relative PATH-Einträge (alle Aufrufer).
- `terminal_open_ssh` lehnt Fenster ab, die weder `main` noch ein losgelöstes Terminal-Fenster (`detached_id`) sind.
  Die Prüfung steht in einer kleinen Funktion mit Unit-Test.
- `ansible_run` nimmt `check: bool`.
- Tests: `which` mit relativem und absolutem Eintrag (der absolute gewinnt), Fensterprüfung (main, `terminal-3` ja;
  `rdp-…`, anderes nein).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T7

### T3 — R-1174: SFTP wartet auf die Anmeldung der Sitzung  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/connection/ssh.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @892839227 2026-11-10T02:11:44+01:00
Review: approve (.ah-out/review/kern-terminal-3/T3.verdict.json)
Änderung:
- Hat die Sitzung einen ControlPath, wartet jeder SFTP-Befehl, bis der Socket existiert (Polling 250 ms, Deckel
  120 s). Endet die Sitzung vorher oder läuft der Deckel ab: Fehler „The session is not signed in yet“, der Nutzer
  aktualisiert danach. Ohne ControlPath (Windows) wie heute.
- `pty.rs` wird nicht geändert (überlappt `feature/klein-kommentare-desktop-1`).
- Tests: Socket erscheint nach kurzer Zeit (Befehl läuft), erscheint nie (Fehler nach dem Deckel, im Test kurz),
  Sitzung endet beim Warten; `control_socket_of` liest den Socket aus dem SFTP-argv (`connection/ssh.rs`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T7

### T4 — R-1144: Rückfrage vor mehrzeiligem Einfügen  [~] (verschoben in kern-terminal-4: überlappt feature/arch-namen (types.ts, dictionaries.ts))
Komponente: desktop-ui · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/components/settings/TerminalSection.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts
Änderung:
- `TerminalPrefs` bekommt `confirm_multiline_paste` (Standard true, serde default); die UI-Typen und Vorgaben folgen.
- Einfügen von Text mit Zeilenumbruch fragt, wenn die Einstellung an ist: Anzahl der Zeilen, „Einfügen“ /
  „Abbrechen“. Einzeiliger Text wie heute.
- Schalter in den Terminal-Einstellungen (DE/EN).
- Tests: mehrzeilig fragt, Abbrechen fügt nichts ein, Bestätigen fügt ein, Einstellung aus fügt sofort ein; Rust:
  fehlendes Feld nimmt den Standard.
- Begründung sieben Dateien: Einstellung über beide Seiten plus Dialog.
Verify: bash scripts/dev/verify.sh desktop-ui desktop-rs --strict
Doku: → T7

### T5 — R-1175: Broadcast an keine Sitzung meldet sich  [~] (verschoben in kern-terminal-4: überlappt feature/arch-namen (dictionaries.ts))
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts
Änderung: `runSnippet` liest die Zahl aus `terminalBroadcast`; bei 0 eine Statusmeldung „An keine Sitzung gesendet“
(DE/EN). Test: 0 meldet, 2 meldet nichts.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/terminals.test.ts
Doku: keine (Rückmeldung ohne dokumentiertes Verhalten)

### T6 — R-1159: Eintrag im Sitzungsverlauf endet mit dem eingebetteten SSH-Terminal  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts
Änderung:
- `connectEmbedded` hängt die von `markConnectionUsed` geöffnete Sitzung an den Tab. Endet dessen Programm oder wird
  der Tab geschlossen, endet die Sitzung (Server- oder lokaler Verlauf wie `markRdpExit`), einmal; danach
  `sessionsChanged()`. „Neu verbinden“ beginnt keinen neuen Eintrag.
- Tests: Programmende beendet den Eintrag, Schließen beendet ihn, zweites Ende ruft nichts.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/connectFlow.test.ts
Doku: → T7

### T7 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/index.html, docs/en/admin/index.html, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-terminal-3.md
Änderung: DE+EN: Rückfrage beim Einfügen und ihr Schalter, Dateien-Panel wartet auf die Anmeldung, Sitzungsverlauf
des eingebetteten Terminals; Entwicklerdoku: `ansible_run` mit `check` (bool), Fensterprüfung von
`terminal_open_ssh`, PATH-Suche nur absolut. CHANGELOG-Eintrag neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- R-1164 fährt nicht mit (pty.rs überlappt feature/klein-kommentare-desktop-1) → tasks/kern-terminal-4.md.
- R-1165: erlaubt sind main und losgelöste Terminal-Fenster, weil deren „Neu verbinden“ terminal_open_ssh ruft.
- R-1144: Rückfrage als Einstellung, Standard an (Kevin 2026-11-10: Empfehlungen übernommen).
- R-1174: Warten in Rust statt Bereitschafts-Abfrage in der UI (Spec, Trade-offs).
