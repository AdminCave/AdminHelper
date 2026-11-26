# Desktop unter Windows: GUI-Subsystem, Konsolen-Start gehaertet — Task-Ledger
Status: bereit · Branch: feature/kern-desktop-5 · Review: pro Task
Spec: docs/features/kern-desktop-5.md (Roadmap R-0867, R-0854)
Heavy: windows — nur Windows-Pfade (terminal.rs cfg(windows), Subsystem); CI-Jobs rust-windows, keine Windows-Box im Pool
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-25 (Notizen R-0854, R-0867): faellig.
- T1: das Programm und wt startet der Desktop ueber `which_in` (nur absolute PATH-Eintraege, `<name>` und `<name>.exe`, kein PATHEXT); ein reines `ssh.cmd`/`ansible-playbook.bat` gilt daher als nicht gefunden. Bewusst: die Spec waehlt `which`, ein PATHEXT-Shim waere wieder ein Startweg ueber cmd.
- T2: auch `sftp.rs` (`Channel::open`) bekommt `CREATE_NO_WINDOW`: ssh mit umgeleiteten Pipes oeffnet unter dem GUI-Subsystem sonst je SFTP-Aktion ein eigenes Konsolenfenster. Die uebrigen Spawns geprueft: ansible.rs setzt das Flag schon, mstsc ist ein GUI-Programm, der Launcher startet DETACHED, der Rest ist unix-only oder Test.

### T1 — Windows-Konsole: Programm per absolutem Pfad, cmd mit /D (R-0867)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/terminal.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @12f56ccec 2026-11-26T13:55:29+01:00
Review: approve (.ah-out/review/kern-desktop-5/T1.verdict.json)
Änderung: `open_windows_terminal` löst `command` mit `which` auf (fehlt es: `AppError::Connection`, nichts startet) und gibt wt und cmd den absoluten Pfad; `cmd_console_line` stellt `/D` vor `/S /V:OFF /K`. Tests: die bestehenden `cmd_console_line_*`-Erwartungen und `run_once_line` auf `/D`; neuer Test, dass ein Programm nur im Arbeitsverzeichnis nicht aufgelöst wird und `open_windows_terminal` dann ablehnt (Auflösung als testbare Funktion über `which_in`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- terminal::
Doku: → T2

### T2 — Release-Build im GUI-Subsystem, icacls ohne Konsole (R-0854)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/terminal.rs, changelog.d/kern-desktop-5.md, apps/desktop/src-tauri/src/sftp.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @bb31c1546 2026-11-26T14:00:40+01:00
Review: approve (.ah-out/review/kern-desktop-5/T2.verdict.json)
Änderung: `#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]` in `main.rs`; `icacls` mit `CREATE_NO_WINDOW`; Kommentar an `spawn_in_new_console` nachziehen. Test `release_build_has_no_console` in `main.rs`: der Quelltext (CRLF normalisiert) trägt das Attribut als erstes inneres Attribut. CHANGELOG-Fragment für beide Zeilen, neutral und umlautfrei.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- release_build_has_no_console
Doku: changelog.d/kern-desktop-5.md
Abhängt von: T1
