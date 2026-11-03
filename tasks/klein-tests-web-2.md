<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-web-2 — Task-Ledger
Status: erledigt · Branch: feature/klein-tests-web-2 · Review: am Ende
Spec: docs/features/klein-tests-web-2.md (Roadmap R-1108)
Heavy: none — Test-Konfiguration; die Playwright-Specs fährt der CI-Job frontend_e2e, kein Stack-, Gateway- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Screenshot-Toleranz auf 0.005 verengen (R-1108)  [x]
Komponente: web · Dateien: apps/web/playwright.config.ts, docs/developer/webui.html, docs/en/developer/webui.html
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @b363b891 2026-11-03T13:55:04+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-web-4 T8 2026-11-03: 6 von 7 alten Baselines bestanden gegen das neue Design bei 0.02
Änderung: `maxDiffPixelRatio` (`playwright.config.ts:69`) 0.02 → 0.005; die zwei Doku-Sätze zur Toleranz folgen. Beleg zusätzlich: lokal `npx playwright test --project=chromium tests/e2e/smoke.spec.ts tests/e2e/login.spec.ts` grün (Summary im Commit-Body), Gegenprobe: mit 0.001 rot; Abschluss: CI `frontend_e2e` grün.
Verify: bash scripts/dev/verify.sh web --strict
Doku: docs/developer/webui.html + docs/en/developer/webui.html (Toleranz)
