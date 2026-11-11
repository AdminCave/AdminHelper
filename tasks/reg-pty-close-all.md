# reg-pty-close-all — Task-Ledger
Status: aktiv · Branch: feature/reg-pty-close-all · Review: am Ende
Spec: docs/features/reg-pty-close-all.md (Roadmap R-1217)
Heavy: none — nur ein Unit-Test im Desktop-Backend; Windows prüft die PR-CI (rust-windows)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1217: close_all_of-Test wartet unter Windows auf die Cursor-Abfrage  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs
Beweis: main-CI Lauf 42634439943 Versuch 1, rust-windows: pty::tests::close_all_of_a_window_leaves_the_others_running panicked at src\pty.rs:557:41 (next: the session answers in time), grün im Rerun · Dedup-Key: reg:desktop-rs:pty.rs:close_all_of
Änderung: `close_all_of_a_window_leaves_the_others_running` ruft `until_ready` für beide Sitzungen vor dem ersten `close_all_of("main")` auf, wie `a_window_that_is_gone_hands_its_sessions_back_to_main`; Kommentar mit dem Warum. Der Fund ist zeitabhängig und nur unter Windows: lokal beweist das Verify, dass der Test unter Linux grün bleibt, den Windows-Beweis liefern die Jobs rust-windows der PR-CI.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty::tests::close_all_of_a_window_leaves_the_others_running
Doku: keine (nur ein Test)
