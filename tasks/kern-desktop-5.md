# Desktop unter Windows: GUI-Subsystem, Konsolen-Start gehaertet — Task-Ledger
Status: geplant · Branch: feature/kern-desktop-5 · Review: pro Task
Spec: docs/features/kern-desktop-5.md (Roadmap R-0867, R-0854)
Heavy: windows — nur Windows-Pfade (terminal.rs cfg(windows), Subsystem); CI-Jobs rust-windows, keine Windows-Box im Pool
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-25 (Notizen R-0854, R-0867): faellig.

### T1 — Windows-Konsole: Programm per absolutem Pfad, cmd mit /D (R-0867)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/terminal.rs
Änderung: `open_windows_terminal` löst `command` mit `which` auf (fehlt es: `AppError::Connection`, nichts startet) und gibt wt und cmd den absoluten Pfad; `cmd_console_line` stellt `/D` vor `/S /V:OFF /K`. Tests: die bestehenden `cmd_console_line_*`-Erwartungen und `run_once_line` auf `/D`; neuer Test, dass ein Programm nur im Arbeitsverzeichnis nicht aufgelöst wird und `open_windows_terminal` dann ablehnt (Auflösung als testbare Funktion über `which_in`).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- terminal::
Doku: → T2

### T2 — Release-Build im GUI-Subsystem, icacls ohne Konsole (R-0854)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/main.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/terminal.rs, changelog.d/kern-desktop-5.md
Änderung: `#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]` in `main.rs`; `icacls` mit `CREATE_NO_WINDOW`; Kommentar an `spawn_in_new_console` nachziehen. Test `release_build_has_no_console` in `main.rs`: der Quelltext (CRLF normalisiert) trägt das Attribut als erstes inneres Attribut. CHANGELOG-Fragment für beide Zeilen, neutral und umlautfrei.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- release_build_has_no_console
Doku: changelog.d/kern-desktop-5.md
Abhängt von: T1
