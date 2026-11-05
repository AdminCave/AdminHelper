<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-3 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-3 · Review: pro Task
Spec: docs/features/kern-deps-3.md (Roadmap R-1039, R-1040)
Heavy: linux-full — WebdriverIO 10 in der Desktop-GUI-E2E; den GUI-Lauf fährt der Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Web: npm-Pakete auf aktuell, Lock neu (R-1039)  [x]
Komponente: web · Dateien: apps/web/package.json, apps/web/package-lock.json, apps/web/vitest.config.ts, apps/web/vitest.setup.ts, changelog.d/kern-deps-3.md, apps/web/src/lib/api/mocks.contract.test.ts, apps/web/src/lib/components/ui/Input.svelte, apps/web/src/lib/stores/auth.test.ts, apps/web/src/lib/components/ui/ConfirmDialog.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @bb474f41 2026-11-05T06:19:01+01:00
Review: approve (.ah-out/review/kern-deps-3/T1.verdict.json)
Änderung: Jedes direkte Paket auf das aktuelle Release (Spec-Tabelle, beim Bau neu mit `npm outdated`), TypeScript bleibt 6.0; vitest/coverage-v8 5, jsdom 30, jest-dom 7 (dazu `@testing-library/dom` als Peer, falls nicht schon da), Playwright 1.64. Lock mit `npm install`. Config, Setup oder Tests nur, wo ein Release es verlangt (Spec, Externe Integrationen); Entscheidungen zu `clearMocks` unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh web --strict
Doku: changelog.d/kern-deps-3.md

### T2 — Desktop-UI: npm-Pakete auf aktuell, Lock neu, Lizenztabelle (R-1039)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, apps/desktop/ui/vitest.config.ts, apps/desktop/ui/vitest.setup.ts, THIRD_PARTY_LICENSES.md, changelog.d/kern-deps-3.md
Änderung: Wie T1 für die Desktop-UI, dazu @testing-library/svelte 5.4 und @vitest/ui 5; die Tauri-JS-Pakete bleiben im Gleichschritt mit den Crates in `Cargo.lock` (Major.Minor). Abschnitt 4 von `THIRD_PARTY_LICENSES.md` mit den ausgelieferten Versionen (`license-checker --production`), die Geist-Schriften mit ihrer Lizenz ergänzt.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: THIRD_PARTY_LICENSES.md · changelog.d/kern-deps-3.md

### T3 — Desktop-E2E: WebdriverIO 10, undici-Override prüfen (R-1040)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json, apps/desktop/e2e/wdio.conf.js, changelog.d/kern-deps-3.md
Änderung: `webdriverio` und alle `@wdio/*` auf 10.x (der Pin von `@wdio/junit-reporter` zieht mit), eslint/globals auf aktuell. Das Override `webdriver.undici` entfällt, wenn `npm ls undici` ohne es nur Versionen ≥ 8.12.3 zeigt; sonst bleibt es mit Begründung unter `## Entscheidungen`. Die übrigen Overrides ebenso prüfen. `wdio.conf.js` und Specs nur, wo wdio 10 es verlangt (Spec).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: changelog.d/kern-deps-3.md

## Entscheidungen
- T1: Vitest 5 setzt `clearMocks: true`. Zwei Testdateien lasen den beim Import registrierten Auth-Failure-Handler aus `mock.calls` jedes Tests; sie lesen ihn jetzt einmal auf Modulebene. Den alten Standard (`clearMocks: false`) setzen wir nicht: isolierte Mock-Aufrufe je Test sind der gewollte neue Standard.
- T1: `@testing-library/dom` ist neu direkte devDependency (Pflicht-Peer von jest-dom 7). `npm audit` zeigt denselben Stand wie `main` (12, nichts ab high; minimatch über eslint, deepmerge).
- T1: Prettier 3.9 formatiert zwei Dateien anders (Union-Typ in einer Zeile, schließendes `</textarea>`); übernommen.
