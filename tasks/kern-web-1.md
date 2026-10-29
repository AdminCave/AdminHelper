<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-1 — Task-Ledger
Status: bereit · Branch: feature/kern-web-1 · Review: am Ende
Spec: docs/features/kern-web-1.md (Roadmap R-0923, R-0924)
Heavy: none — nur apps/web (API-Client), hermetische vitest-Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@2489bfc4`; Pfade ohne Präfix unter `apps/web/src/lib/`. Neue Code-Strings englisch,
CHANGELOG umlautfrei in `changelog.d/kern-web-1.md`. `security` zusätzlich (Sitzungslogik).

### T1 — API-Client: Refresh je Sitzung, Anmeldung beginnt immer eine Sitzung (R-0923, R-0924)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts, changelog.d/kern-web-1.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @5c343dad 2026-10-29T21:47:40+01:00
Review: am Ende (Branch-Review)
Änderung: `tryRefresh` (`api/client.ts:95`) teilt `refreshInFlight` nur mit Aufrufern derselben Sitzung; ein 401 einer neueren Sitzung startet einen eigenen Refresh. `login()` (`api/auth.ts:8`) beginnt immer eine neue Sitzung, auch wenn noch ein Token gehalten wird. Tests zuerst rot: (a) ohne Web Locks, Refresh der alten Sitzung antwortet nach der neuen Anmeldung, ein 401 der neuen Sitzung ruft `onAuthFailure` nicht; (b) Anmeldung bei gehaltenem Token, eine Anfrage der alten Sitzung wird nach der Anmeldung mit 401 beantwortet und lässt die neue Sitzung stehen.
Beweis: R-0923 reviewer web-stores-refactor T5 2026-10-28 · api/client.ts tryRefresh; R-0924 security-branch web-stores-refactor 2026-10-28 · api/client.ts:57, stores/auth.ts:68 (heute :56, :68)
Dedup-Key: bug:web:api/client.ts:refresh-in-flight-across-sessions, bug:web:api/client.ts:login-session-with-held-token
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts
Doku: changelog.d/kern-web-1.md

### T2 — Abschlussprüfung: Test der finally-Bedingung, Spec nachgezogen (R-0923)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts, docs/features/kern-web-1.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @57b30aba 2026-10-29T21:57:50+01:00
Review: am Ende (Branch-Review)
Änderung: Test „the end of the old refresh keeps the new session sharing its own“: endet der Refresh der alten Sitzung, während der der neuen offen ist, teilt ein weiterer 401 der neuen Sitzung deren Refresh (`api/client.ts:126`, Gegenprobe mit unbedingtem `refreshInFlight = null`: 1 failed). Kommentare auf 100 Zeichen umbrochen; Spec nennt `setAccessToken` statt `startSession` in `login()`.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts
Doku: docs/features/kern-web-1.md

## Entscheidungen
- T1: Der Test „a new token within the same session still ends it on a failed refresh“ (`client.test.ts`) hielt das
  Verhalten fest, das R-0924 als Fehler meldet (ein `setAccessToken` bei gehaltenem Token blieb in der alten
  Sitzung). Gewollte Verhaltensänderung: ersetzt durch „a login while a token is held starts a new session“.
- T1: Die Sitzung eines Refresh gilt ab dem Aufruf von `tryRefresh`, nicht erst ab der Web-Lock-Vergabe; ein
  Refresh, der über eine Anmeldung hinweg auf die Sperre wartet, setzt kein Token der neuen Sitzung.
- T1: `api/auth.ts` bleibt unverändert: `setAccessToken` beginnt die Sitzung selbst, `login()` ist sein einziger
  Aufrufer.
