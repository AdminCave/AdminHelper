<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ci-4 — Task-Ledger
Status: geplant · Branch: feature/klein-ci-4 · Review: am Ende
Spec: docs/features/klein-ci-4.md (Roadmap R-1396)
Heavy: none — Workflow-Schritte, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1396: doppelte Testschritte für .github/scripts/*_test.sh aus ci.yml entfernen  [ ]
Komponente: scripts · Dateien: .github/workflows/ci.yml
Review: am Ende (Branch-Review)
Beweis: kevin 2026-11-12 · ci.yml:1285-1292 (vier Schritte nach `Hermetic shell tests`), run.sh:695 führt dieselben vier Tests
Änderung: Die Schritte `retry.sh test`, `apt_archives_verify.sh test`, `tauri_cli_pins.sh test` und `cache_settings.sh test` im Job mit `run.sh unit --strict --only scripts` entfallen. Vorher belegen, dass alle vier in `AH_SCRIPT_TESTS_DEFAULT` stehen und der `scripts`-Block sie fährt.
Verify: bash scripts/dev/verify.sh scripts --strict -- .github/scripts/retry_test .github/scripts/apt_archives_verify_test .github/scripts/tauri_cli_pins_test .github/scripts/cache_settings_test
Doku: keine (cicd.html nennt den Test, nicht den CI-Schritt)
