<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-3 — Task-Ledger
Status: bereit · Branch: feature/kern-web-3 · Review: pro Task
Spec: docs/features/kern-web-3.md (Roadmap R-0989, R-0975, R-0980)
Heavy: none — nur Web-Client-Logik und Vertragstests, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@66d3ef6f`, vor dem Schreiben neu greppen. Neue Code-Strings englisch,
CHANGELOG umlautfrei in `changelog.d/kern-web-3.md`.

### T1 — Unlesbare Idle-Zeit beendet die Sitzung beim Laden (R-0989)  [x]
Komponente: web · Dateien: apps/web/src/lib/idle.ts, apps/web/src/lib/idle.test.ts, docs/admin/benutzer.html, docs/en/admin/users.html, changelog.d/kern-web-3.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @9b9e75c9 2026-10-30T17:01:46+01:00
Review: approve (.ah-out/review/kern-web-3/T1.verdict.json)
Beweis: Abschlusspruefung kern-web-2 2026-10-30 · Code-Lesung feature/kern-web-2@32dcd895 apps/web/src/lib/idle.ts:35-42 · Dedup-Key: bug:web:idle:nan-timestamp
Änderung: Im `restored`-Zweig (`idle.ts:35-42`) gilt ein gespeicherter Wert, dessen Zahl nicht endlich ist, als unbekanntes Alter: `onIdle` sofort; `null` bleibt ohne Wirkung. Test zuerst rot: `restored` mit `'abc'` unter `adminhelper_last_activity` ruft `onIdle`.
Verify: bash scripts/dev/verify.sh web --strict -- idle
Doku: docs/admin/benutzer.html + docs/en/admin/users.html (Satz zur Abmeldung beim Laden), changelog.d/kern-web-3.md

### T2 — withAuthLock ohne Web Locks: Aufrufe im Tab nacheinander (R-0975)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.crosstab.test.ts, apps/web/src/lib/api/client.test.ts, docs/developer/webui.html, docs/en/developer/webui.html
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @31d55135 2026-10-30T17:09:38+01:00
Review: approve (.ah-out/review/kern-web-3/T2.verdict.json)
Änderung: `withAuthLock` (`client.ts:88-93`) hängt `fn` ohne `navigator.locks` an eine modulweite Promise-Kette (ein Fehler von `fn` bricht die Kette nicht); Kommentar nachziehen. Test zuerst rot: ohne Lock-Manager laufen zwei `withAuthLock`-Aufrufe nicht überlappend.
Verify: bash scripts/dev/verify.sh web --strict -- client
Doku: docs/developer/webui.html, docs/en/developer/webui.html (Fall ohne Web Locks)

### T3 — Web-Vertragstest: fehlende Pflichtfelder in Anfragen (R-0980)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/types.contract.test.ts, apps/web/src/lib/api/types.ts, docs/developer/cicd.html, docs/en/developer/cicd.html, docs/features/kern-web-3.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @1a701198 2026-10-30T17:13:28+01:00
Review: approve (.ah-out/review/kern-web-3/T3.verdict.json)
Änderung: `compare()` (`types.contract.test.ts:285-321`) meldet bei `request` jedes `required`-Feld des Schemas, das der TS-Typ nicht trägt und `omit` nicht nennt (`<key>: required schema field missing`); Selbsttest dazu. Echte Lücken: Typ ergänzen oder `omit` mit Grund (Entscheidung im Ledger).
Verify: bash scripts/dev/verify.sh web --strict -- types.contract
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (Regeln für Anfragen, gilt auch für die Desktop-Zeile)

### T4 — Desktop-UI-Vertragstest: fehlende Pflichtfelder in Anfragen (R-0980)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/api/types.contract.test.ts, apps/desktop/ui/src/lib/api/types.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @665a0fd2 2026-10-30T17:15:13+01:00
Review: approve (.ah-out/review/kern-web-3/T4.verdict.json)
Änderung: dieselbe Prüfung wie T3 in der Desktop-Kopie von `compare()`; Lücken wie in T3.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- types.contract
Doku: keine (Regeln in cicd.html zieht T3 nach)

## Entscheidungen
