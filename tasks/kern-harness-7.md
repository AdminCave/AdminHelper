# tauri-cli-Pin des Bootstraps im Gleichschritt — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-7 · Review: am Ende
Spec: docs/features/kern-harness-7.md (Roadmap R-1294)
Heavy: none — nur Harness-Skripte und Doku; der Bootstrap wirkt erst beim nächsten Backen einer Vorlage (Kevins Wort)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1294: Bootstrap-Pin anheben und von toolchain-lockstep.sh prüfen lassen  [ ]
Komponente: scripts · Dateien: scripts/vm/bootstrap_linux.sh, scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Test zuerst: die Fixture bekommt eine tauri-cli-Zeile in `ci.yml`; Fälle gleich (grün, Ausgabe nennt
beide), Drift (rot, Meldung nennt beide Stellen), kein Bootstrap-Standard (rot). Dann Prüfung 2c in
`toolchain-lockstep.sh`, Pin `2.12.4` im Bootstrap und dessen Installation, sobald `cargo tauri --version` nicht
`tauri-cli $TAURI_CLI_VERSION` nennt.
Beweis: reviewer ci-8 branch 2026-11-10, feature/ci-8@50f6920e4 scripts/vm/bootstrap_linux.sh:24 · Dedup-Key: ref:ci:tauri-cli-pin:bootstrap
Verify: bash scripts/dev/verify.sh scripts --strict -- toolchain_lockstep_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (Lockstep-Satz)

## Entscheidungen
