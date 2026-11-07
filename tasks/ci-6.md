# CI-Services und Playwright-Runner auf aktuellem Stand — Task-Ledger
Status: bereit · Branch: feature/ci-6 · Review: am Ende
Spec: docs/features/ci-6.md (Roadmap R-1134, R-1136, R-1137)
Heavy: none — nur `ci.yml` und Doku; Beweis ist die PR-CI selbst (Services und Runner gelten im PR-Lauf)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — ci.yml: Services auf redis:8-alpine und postgres:18-alpine (R-1136, R-1137)  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2adba051c 2026-11-07T20:45:54+01:00
Review: am Ende (Branch-Review)
Änderung: Die zwei `redis:7-alpine`- und die sieben `postgres:17-alpine`-Services in `ci.yml` auf `redis:8-alpine` bzw. `postgres:18-alpine`, die Hauptversionen von `docker-compose.yml`. `server.html:223` DE+EN: CI-Postgres ist 18, „Umstellung auf 18 folgt“ entfällt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/server.html DE+EN

### T2 — ci.yml: frontend-e2e auf ubuntu-26.04 (R-1134)  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d765e4fd0 2026-11-07T20:55:31+01:00
Review: am Ende (Branch-Review)
Änderung: Job `frontend-e2e` auf `runs-on: ubuntu-26.04`, der Kommentar zu Playwright 1.60 entfällt. `cicd.html:42` DE+EN: der Satz zur Ausnahme für `frontend-e2e` entfällt. `changelog.d/ci-6.md` (`### Changed`, umlautfrei) für T1 und T2.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html DE+EN · changelog.d/ci-6.md
