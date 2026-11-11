# Terminal-Tab: Schließen trotz unbeantworteter Cursor-Abfrage — Task-Ledger
Status: erledigt · Branch: feature/kern-terminal-6 · Review: am Ende
Spec: docs/features/kern-terminal-6.md (Roadmap R-1312)
Heavy: none — nur Desktop-Rust (pty), kein Stack-, Gateway-, PKI- oder Install-Pfad; den Windows-Pfad prüft der CI-Job rust-windows
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1312: eine geschlossene Sitzung mit offener Cursor-Abfrage endet  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs, changelog.d/kern-terminal-6.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f67a1f733 2026-11-11T14:12:47+01:00
Review: am Ende (Branch-Review)
Änderung: Test zuerst (rot unter Unix lokal, unter Windows per `rust-windows` auf einem Wegwerf-Branch): Sitzung mit
lauschender Senke, die Abfrage bleibt unbeantwortet, `close_all_of`, die Sitzung muss das Registry verlassen. Dann
der Merker in `Session` (gesetzt im Lese-Thread, gelöscht in `PtyRegistry::write` bei einer Cursor-Antwort), und
`Session::close` schreibt die offene Antwort vor dem Beenden. Plus ein Test, dass eine Antwort über `write` den
Merker löscht.
Beweis: reviewer branch reg-pty-close-all 2026-11-11, feature/reg-pty-close-all@b5fd6c064 Hinweis 1; main@8279bacf8 pty.rs Lese-Thread (Antwort nur bei `!listening`) · Dedup-Key: bug:desktop-rs:pty.rs:close_all_of
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty::tests
Doku: changelog.d/kern-terminal-6.md (keine Seite beschreibt die Cursor-Abfrage)

## Entscheidungen
- T1: Windows-Beweis vor dem Fix: nur der neue Test auf einem Wegwerf-Branch (27dde8067), CI-Lauf 43026363748, Job
  rust-windows rot (`the session stays in the registry`, 923 passed; 1 failed); lokal unter Linux ebenso rot
  (Timeout). Mit dem Fix grün. Der Merker gilt auf allen Plattformen; das automatische Antworten ohne Zuhörer bleibt
  Windows-only.
