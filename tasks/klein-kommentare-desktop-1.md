<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-desktop-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-kommentare-desktop-1 · Review: am Ende
Spec: docs/features/klein-kommentare-desktop-1.md (Roadmap R-1156)
Heavy: none — nur ein Kommentar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1156: Kommentar zu `killer` nennt das Restfenster  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs
Beweis: security-Review arch-ssh-terminal branch 2026-11-05 (Nit) · Dedup-Key: ref:desktop:pty.rs:killer
Änderung: Der Doc-Kommentar von `Session::killer` nennt das Restfenster zwischen `child.wait()` und `killer.take()` (ein gleichzeitiges `close()` kann die gereapte PID noch signalisieren) und warum es hingenommen wird. Kein Verhalten ändert sich.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (interner Kommentar)
