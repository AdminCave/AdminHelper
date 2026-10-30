<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-web-2 — Task-Ledger
Status: geplant · Branch: feature/kern-web-2 · Review: am Ende
Spec: docs/features/kern-web-2.md (Roadmap R-0890)
Heavy: none — nur die Web-Logik beim Laden, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@b61444fd`, vor dem Schreiben neu greppen. CHANGELOG umlautfrei.

### T1 — Idle beim Laden: eine Zeit aus der Zukunft meldet ab (R-0890)  [ ]
Komponente: web · Dateien: apps/web/src/lib/idle.ts, apps/web/src/lib/idle.test.ts, docs/admin/benutzer.html, docs/en/admin/users.html, changelog.d/kern-web-2.md
Beweis: Code-Lesung `apps/web/src/lib/idle.ts:34-39` (`Date.now() - Number(stored) >= limitMs` ist bei einer Zeit nach der Uhr negativ) · Dedup-Key: bug:web:idle:future-timestamp · HEAD: b61444fd
Semantik: `docs/admin/benutzer.html:67` „Liegt die letzte Bedienung dort länger als diese Dauer zurück, endet die Sitzung beim Laden sofort mit demselben Hinweis.“ — die Zukunft deckt der Text nicht; Kevin 2026-10-30: abmelden.
Änderung: Im `restored`-Zweig (`idle.ts:34`) ruft `watchIdle` `onIdle` auch, wenn die gespeicherte Zeit nach `Date.now()` liegt; ein nicht lesbarer Wert (`null`) bleibt wie nach einem Login. Test im `describe('restored')` (`idle.test.ts:210`): (e) gespeicherte Zeit 1 ms und 60 min nach `START` → `onIdle` sofort, kein Listener, kein Timer (wie (a)); zuerst rot auf HEAD.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/idle.test.ts
Doku: docs/admin/benutzer.html + docs/en/admin/users.html · changelog.d/kern-web-2.md

## Entscheidungen
