# Terminal-Tab: Schließen trotz unbeantworteter Cursor-Abfrage — Task-Ledger
Status: aktiv · Branch: feature/kern-terminal-6 · Review: am Ende
Spec: docs/features/kern-terminal-6.md (Roadmap R-1312)
Heavy: none — nur Desktop-Rust (pty), kein Stack-, Gateway-, PKI- oder Install-Pfad; den Windows-Pfad prüft der CI-Job rust-windows
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1312: eine geschlossene Sitzung mit offener Cursor-Abfrage endet  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs, changelog.d/kern-terminal-6.md
Änderung: Test zuerst (rot unter Unix lokal, unter Windows per `rust-windows` auf einem Wegwerf-Branch): Sitzung mit
lauschender Senke, die Abfrage bleibt unbeantwortet, `close_all_of`, die Sitzung muss das Registry verlassen. Dann
der Merker in `Session` (gesetzt im Lese-Thread, gelöscht in `PtyRegistry::write` bei einer Cursor-Antwort), und
`Session::close` schreibt die offene Antwort vor dem Beenden. Plus ein Test, dass eine Antwort über `write` den
Merker löscht.
Beweis: reviewer branch reg-pty-close-all 2026-11-11, feature/reg-pty-close-all@b5fd6c064 Hinweis 1; main@8279bacf8 pty.rs Lese-Thread (Antwort nur bei `!listening`) · Dedup-Key: bug:desktop-rs:pty.rs:close_all_of
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty::tests
Doku: changelog.d/kern-terminal-6.md (keine Seite beschreibt die Cursor-Abfrage)

## Entscheidungen
