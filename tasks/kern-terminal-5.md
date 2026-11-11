# Run-Verzeichnis beim App-Ende, Windows-Downloadnamen, Ende der RDP-Sitzung im Verlauf — Task-Ledger
Status: geplant · Branch: feature/kern-terminal-5 · Review: am Ende
Spec: docs/features/kern-terminal-5.md (Roadmap R-1164, R-1272, R-1273)
Heavy: none — nur Desktop-Rust (pty, sftp) und Desktop-UI-Store, kein Stack-, Gateway-, PKI- oder Install-Pfad; die Windows-Pfade prüft der PR-CI-Job rust-windows
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1164: das Run-Verzeichnis eines Tabs geht auch beim App-Ende  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/pty.rs, apps/desktop/src-tauri/src/main.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-terminal-5.md
Änderung: `Session` hält den Pfad aus `Spawn::cleanup`; neue Methode `PtyRegistry::shutdown(grace)`: `close_all()`,
bis `grace` warten, bis die Wait-Threads der Sitzungen mit Run-Verzeichnis fertig sind, dann die übrigen Verzeichnisse
selbst entfernen. `main.rs` (`RunEvent::Exit`) ruft `shutdown(2 s)` statt `close_all()`. Test (Unix, erst rot gegen
`close_all`): ein Programm, das SIGHUP ignoriert, mit Run-Verzeichnis; nach `shutdown` ist das Verzeichnis weg.
Beweis: review kern-terminal-1 2026-11-06; main@495f5797f pty.rs:239–244 (Entfernen nur nach `child.wait()`), main.rs:327 · Dedup-Key: BUG:desktop-rs:pty.rs:ansible_run_dir_exit
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- pty::tests
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Zeile Ansible: Run-Verzeichnis auch beim App-Ende), changelog.d/kern-terminal-5.md

### T2 — R-1272: Download-Namensvorschlag unter Windows nur mit zulässigen Namen  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/sftp.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-terminal-5.md
Änderung: reine Funktion `windows_name` (auf allen Plattformen getestet), angewandt in `suggested_name` nur unter
`cfg(windows)`. Sie macht aus `<>"/|?*` jeweils `_`, schneidet Punkte und Leerzeichen am Ende ab (ohne Rest bleibt
`download`) und setzt bei reservierten Namen (CON, PRN, AUX, NUL, COM1–9, COM¹²³, LPT1–9, LPT¹²³, ohne Rücksicht auf
Groß- und Kleinschreibung, auch mit Endung) `_` vor die erste Endung. Regeln laut Microsoft „Naming Files, Paths, and
Namespaces“ (Spec). Die Tests nehmen Fälle aus der Doku: `NUL.tar.gz`, `com¹`, `a.`, `b `, `x?y`.
Beweis: security-review kern-terminal-3 T1 2026-11-10; main@495f5797f sftp.rs:229 ersetzt nur `\`, `:`, Steuer- und Bidi-Zeichen
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- sftp::tests
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Absatz SFTP, `suggested_name`), changelog.d/kern-terminal-5.md

### T3 — R-1273: RDP im Tab beendet seinen Eintrag im Sitzungsverlauf  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/connectFlow.ts, apps/desktop/ui/src/lib/stores/connectFlow.test.ts, docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-terminal-5.md
Änderung: `openRdp` nimmt wie `openTerminal` ein optionales `onEnd` (`watchEnd`). `connectRdpInTab` beendet die Sitzung
aus `markConnectionUsed` damit einmal, wie `connectEmbedded` (R-1159). Test erst rot: RDP-Tab gestartet, Tab
`disconnected` → `endSession` genau einmal, auch nach einem Neuverbinden nicht noch einmal.
Beweis: kern-terminal-3 T6 2026-11-10; main@495f5797f connectFlow.ts:479 `markConnectionUsed(listed)` ohne Ende · Dedup-Key: BUG:desktop-ui:connectFlow.ts:connectRdpInTab
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- connectFlow terminals
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Verbindungsschritte: RDP im Tab wie SSH), changelog.d/kern-terminal-5.md

## Entscheidungen
