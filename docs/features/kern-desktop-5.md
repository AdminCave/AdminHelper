<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-5 — Desktop unter Windows: GUI-Subsystem, Konsolen-Start gehärtet

Roadmap: R-0867 (SEC), R-0854 (BUG). Zeilenangaben `origin/main@8984d1230`.

## Problem / Motivation
- **R-0867:** Öffnet der Desktop SSH oder Ansible im OS-Terminal unter Windows
  (`apps/desktop/src-tauri/src/terminal.rs:112` `open_windows_terminal`), gibt er den Programmnamen (`ssh`,
  `ansible-playbook`) unverändert an Windows Terminal bzw. an `cmd` weiter (`cmd_console_line`, `terminal.rs:296`).
  Die Suche nach dem Programm macht dann wt bzw. cmd selbst, nach ihren eigenen Regeln. Die Zeile von `cmd`
  trägt kein `/D`.
- **R-0854:** `src/main.rs` trägt kein `windows_subsystem`-Attribut; der Release-Build läuft im Konsolen-Subsystem,
  und neben dem Fenster öffnet sich eine Konsole (Code-Lesung, auf Windows nicht verifiziert).

## Ziel & Nicht-Ziele
- Ziel (R-0867): `open_windows_terminal` löst das Programm vorher mit `terminal::which` auf (nur absolute
  PATH-Einträge) und übergibt wt und cmd den absoluten Pfad; fehlt es, eine Fehlermeldung, nichts startet.
  `cmd_console_line` beginnt mit `/D`.
- Ziel (R-0854): `#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]` in `main.rs`. Ein
  GUI-Prozess, der ein Konsolenprogramm startet, bekäme dafür eine eigene Konsole: `icacls`
  (`src/storage.rs:760`) startet mit `CREATE_NO_WINDOW` wie schon der ssh-Lookup in `ansible.rs`. Der Kommentar an
  `spawn_in_new_console` (`terminal.rs:139`, „The desktop is a console program“) wird nachgezogen.
- Nicht-Ziel: der Debug-Build (`cargo test`, `tauri dev`) bleibt Konsolenprogramm; die Wahl zwischen wt und cmd
  bleibt.

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/terminal.rs`, `src/main.rs`, `src/storage.rs`; `changelog.d/kern-desktop-5.md`.

## Datenmodell / API / Migrationen
Keine. Tauri-Commands unverändert.

## Externe Integrationen
- cmd `/D`: learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd.
- `windows_subsystem`: doc.rust-lang.org/reference/runtime.html#the-windows_subsystem-attribute.
- `CREATE_NO_WINDOW` (0x08000000): learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags;
  frpc startet über `tauri-plugin-shell`, das ihn schon setzt (`process/mod.rs:228`, Version 2.6.0).

## Trade-offs & Alternativen
- `SearchPathW` ohne CWD statt `which`: dieselbe Wirkung, aber zusätzlicher FFI-Code; `which` ist schon die
  Suche des eingebetteten Terminals. Empfehlung: `which`.
- wt startet selbst kein Konsolenfenster des Desktops; ob `wt.exe` als Konsolenprogramm kurz eine Konsole zeigt,
  ist ohne Windows-Box nicht verifiziert (nur kosmetisch).

## Risiken & Rollback
Windows-Verhalten ist ohne Windows-Box nur über die CI-Jobs `rust-windows` (Debug-Build, die `cfg(windows)`-Tests
von `terminal.rs`) geprüft; das Subsystem des Release-Builds prüft kein Test im Lauf, nur der Quelltexttest.
Rollback: Revert je Task.

## Doku-Impact
Keine dokumentierte Stelle beschreibt den Konsolen-Start unter Windows oder das Konsolenfenster;
CHANGELOG-Fragment (umlautfrei).

## Offene Fragen
Keine.
