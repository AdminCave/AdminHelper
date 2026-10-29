<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-1 — Task-Ledger
Status: geplant · Branch: feature/kern-web-1 · Review: am Ende
Spec: docs/features/kern-web-1.md (Roadmap R-0923, R-0924)
Heavy: none — nur apps/web (API-Client), hermetische vitest-Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@2489bfc4`; Pfade ohne Präfix unter `apps/web/src/lib/`. Neue Code-Strings englisch,
CHANGELOG umlautfrei in `changelog.d/kern-web-1.md`. `security` zusätzlich (Sitzungslogik).

### T1 — API-Client: Refresh je Sitzung, Anmeldung beginnt immer eine Sitzung (R-0923, R-0924)  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/auth.ts, apps/web/src/lib/api/client.test.ts, changelog.d/kern-web-1.md
Änderung: `tryRefresh` (`api/client.ts:95`) teilt `refreshInFlight` nur mit Aufrufern derselben Sitzung; ein 401 einer neueren Sitzung startet einen eigenen Refresh. `login()` (`api/auth.ts:8`) beginnt immer eine neue Sitzung, auch wenn noch ein Token gehalten wird. Tests zuerst rot: (a) ohne Web Locks, Refresh der alten Sitzung antwortet nach der neuen Anmeldung, ein 401 der neuen Sitzung ruft `onAuthFailure` nicht; (b) Anmeldung bei gehaltenem Token, eine Anfrage der alten Sitzung wird nach der Anmeldung mit 401 beantwortet und lässt die neue Sitzung stehen.
Beweis: R-0923 reviewer web-stores-refactor T5 2026-10-28 · api/client.ts tryRefresh; R-0924 security-branch web-stores-refactor 2026-10-28 · api/client.ts:57, stores/auth.ts:68 (heute :56, :68)
Dedup-Key: bug:web:api/client.ts:refresh-in-flight-across-sessions, bug:web:api/client.ts:login-session-with-held-token
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts
Doku: changelog.d/kern-web-1.md

## Entscheidungen
