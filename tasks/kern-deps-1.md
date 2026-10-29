<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-1 · Review: am Ende
Spec: docs/features/kern-deps-1.md (Roadmap R-0922)
Heavy: linux-full — T3 ändert den Unterbau der Desktop-GUI-E2E (webdriverio → undici), der nur im Sammellauf läuft
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: `npm audit fix` ohne `--force` im Verzeichnis, danach `npm audit --audit-level=high` mit Exit 0
(wie `.github/workflows/audit.yml:99-109`); nur das Lockfile ändert sich.

### T1 — web: undici und vitest im Lockfile anheben (R-0922)  [x]
Komponente: web · Dateien: apps/web/package-lock.json, apps/web/package.json
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @51182b6d 2026-10-29T21:28:28+01:00
Review: am Ende (Branch-Review)
Änderung: `undici` ≥ 7.30.1 (über jsdom) und `vitest`/`@vitest/*` ≥ 4.1.12 im Lockfile; `npm audit --audit-level=high` grün.
Beweis: audit.yml 2026-10-26 (Lauf 40326284489, Job „npm audit“ rot); lokal `npm audit` in apps/web: undici 7.0.0 - 7.30.0 high
Dedup-Key: rel:deps-audit
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (Lockfile eines Testwerkzeugs)

### T2 — desktop-ui: undici und vitest im Lockfile anheben (R-0922)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package-lock.json
Änderung: wie T1 für `apps/desktop/ui`.
Beweis: lokal `npm audit` in apps/desktop/ui: undici 7.0.0 - 7.30.0 high
Dedup-Key: rel:deps-audit
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (Lockfile eines Testwerkzeugs)

### T3 — desktop-e2e: undici und ip-address im Lockfile anheben (R-0922)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/package-lock.json
Änderung: `undici` ≥ 7.30.1 (cheerio) und ≥ 6.29.1 (webdriver), `ip-address` > 10.7.3 im Lockfile; `serialize-javascript` (low, nur mit Major-Sprung von `@wdio/mocha-framework`) bleibt.
Beweis: lokal `npm audit` in apps/desktop/e2e: undici 4.0.0 - 6.29.0 || 7.0.0 - 7.30.0 high
Dedup-Key: rel:deps-audit
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Lockfile eines Testwerkzeugs)

## Entscheidungen
