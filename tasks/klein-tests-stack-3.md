<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-stack-3 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-stack-3 · Review: am Ende
Spec: docs/features/klein-tests-stack-3.md (Roadmap R-1006)
Heavy: linux-full — ändert integration_stack_test.sh (Stack-Lauf); Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Stack-Test: Neuerzeugen nach `down -v` mit frischer PKI (R-1006)  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @15bc11b3 2026-11-02T11:13:12+01:00
Review: am Ende (Branch-Review)
Beweis: R-1006 / R-0899 Rest, klein-tests-stack-2 2026-10-30, docs/features/klein-tests-stack-2.md Nicht-Ziele
Dedup-Key: ref:scripts:integration_stack_test.sh:recreate-after-wipe
Änderung: neuer letzter Abschnitt `recreate_after_wipe`: Root-Fingerabdruck vor dem Leeren merken, `e2e_dc down -v --remove-orphans`, `e2e_up gateway`, `e2e_wait_enroll_plane`; dann ok/bad für (a) anderer Root-Fingerabdruck, (b) altes Geräte-Zertifikat vom Gateway abgewiesen (400), (c) frische Anmeldung auf :8444 liefert ein vom Gateway angenommenes Zertifikat (401), (d) Admin-Login mit `ADMIN_PASSWORD`. Jede FAIL-Zeile ohne PIDs/Zeiten (stabiler Marker).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Tests)
