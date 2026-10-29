<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-desktop-1 — Task-Ledger
Status: geplant · Branch: feature/klein-ref-desktop-1 · Review: pro Task
Spec: docs/features/klein-ref-desktop-1.md (Roadmap R-0856, R-0873, R-0875, R-0937)
Heavy: none — interne Prüfungen, Aufräumpfad und Tests im Desktop, keine Journey, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — frpc: Vorprüfung vor head_left_behind, Typalias im Test (R-0856, R-0875)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs
Änderung: `head_left_behind` prüft `run_dir` zuerst mit `symlink_metadata` (wie `empty_run_dir`): ist es kein Verzeichnis (Symlink, Junction, Datei), loggt es eine Warnung und liefert `None`, ohne `visitor.toml` zu lesen. Test: ein Symlink als `run_dir` auf einen Ordner mit gültigem Kopf stoppt nichts (unter `cfg(unix)`). Im Test `the_first_reconciliation_stops_nothing_behind_a_head_that_is_not_the_desktops` ersetzt ein Typalias den Typ von `cases`; `cargo clippy --all-targets -- -D warnings` läuft danach sauber (Beleg zusätzlich zum Verify).
Beweis: R-0856 Code-Lesung origin/main frpc.rs head_left_behind; R-0875 clippy --all-targets frpc.rs:3510
Dedup-Key: ref:desktop:frpc.rs:head-left-behind-symlink
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc
Doku: keine (interne Prüfung)

### T2 — ansible: Laufordner-Hygiene (R-0873)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/ansible.rs
Änderung: `create_run_dir` deklariert `mut builder` nur unter `cfg(unix)`; das Aufräumskript löscht den von `confined_run_dir` geprüften kanonischen Ordner (`launch_ansible_with` reicht kanonische Dateipfade an `start` weiter, `linux_run_script` leitet den Ordner daraus ab) statt des rohen Elternverzeichnisses; `scratch()` und `stub_ansible_playbook` legen ihre Verzeichnisse über `create_run_dir`/ein eigenes eindeutiges Verzeichnis an statt unter festen Namen. Test: ein Inventarpfad über einen Symlink auf den Laufordner löscht den Ordner, nicht den Symlink-Namen. Keine Eigentümerprüfung (Spec, Trade-offs).
Beweis: Code-Lesung origin/main ansible.rs:149, 353, 517, 772
Dedup-Key: ref:desktop:ansible.rs:run-dir-hygiene
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- ansible
Doku: keine (interner Aufräumpfad)

### T3 — shellQuote: % quoten (R-0937)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/shell.ts, apps/desktop/ui/src/lib/utils/shell.test.ts
Änderung: `%` fliegt aus `SAFE`, der Kommentar zur fish-Ausnahme entfällt; Test: `%self` und ein Wert mit `%` kommen gequotet heraus, der `BARE`-Eintrag mit `%2B` wandert nach `QUOTED`.
Beweis: Code-Lesung origin/main shell.ts:7
Dedup-Key: ref:desktop-ui:shell.ts:safe-percent
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/utils/shell.test.ts
Doku: keine (nicht sichtbar, Wert nie mit %)

## Entscheidungen
- 2026-10-29 R-0873: keine Eigentümerprüfung in `confined_run_dir` (bräuchte `libc`; ein fremder 0700-Ordner ist nicht traversierbar, nur root käme hinein).
- 2026-10-29 R-0872: nicht in diesem Zug, schon durch `dd1f9b01` behoben; Zeile wartet auf Kevins Wort.
