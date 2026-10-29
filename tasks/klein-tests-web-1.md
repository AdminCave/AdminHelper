<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-web-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-tests-web-1 · Review: pro Task
Spec: docs/features/klein-tests-web-1.md (Roadmap R-0888, R-0891)
Heavy: none — Unit-Tests im Web-Frontend, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — App.idle.test: „0 = aus“ über das Standardlimit hinaus (R-0888)  [ ]
Komponente: web · Dateien: apps/web/src/App.idle.test.ts
Änderung: Fall (b) lässt 31 Minuten plus ein Prüfintervall (`CHECK`) vergehen statt 10; ein Rückfall auf `|| 30` färbt ihn rot (Gegenprobe im Test-Lauf, danach zurückgenommen).
Beweis: R-0888 Code-Lesung App.idle.test.ts:110
Dedup-Key: ref:web:App.idle.test.ts:zero-off-window
Verify: bash scripts/dev/verify.sh web --strict -- src/App.idle.test.ts
Doku: keine (Test)

### T2 — client.crosstab.test: scheiternder Logout und /auth/-Pfade ohne Refresh (R-0891)  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/client.crosstab.test.ts
Änderung: Zwei Fälle in `logout across tabs`: (1) der Logout wird mit 500 beantwortet, endet ohne Fehler, löscht das Token und gibt die Sperre frei (ein Refresh eines anderen Tabs läuft danach); (2) eine 401-Antwort auf einen `/auth/`-Pfad (Logout unter der Sperre und `me`) löst nie einen Refresh aus. Gegenprobe: `!path.includes('/auth/')` in `client.ts` entfernt färbt (2) rot.
Beweis: R-0891 Code-Lesung client.crosstab.test.ts:217, lib/api/auth.ts:21
Dedup-Key: ref:web:auth.ts:lock-tests-missing
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.crosstab.test.ts
Doku: keine (Test)

## Entscheidungen
