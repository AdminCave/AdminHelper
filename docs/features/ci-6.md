# ci-6: CI-Services und Playwright-Runner auf aktuellem Stand

Zug `tasks/ci-6.md`, Roadmap R-1134, R-1136, R-1137 (Kevin 2026-11-02: alles auf aktuelle LTS/Stable).

## Problem / Motivation

- **R-1136:** Der Stack fährt `redis:8-alpine` (`docker-compose.yml:406`), die CI-Services in
  `.github/workflows/ci.yml:60,321` noch `redis:7-alpine`. Die CI prüft damit eine andere Redis-Hauptversion als die,
  die ausgeliefert wird.
- **R-1137:** Ebenso Postgres: Der Stack ist seit kern-pg-1 (#401) auf `postgres:18-alpine` (`docker-compose.yml:13`),
  die sieben Services in `ci.yml:44,217,254,308,411,451,493` auf `postgres:17-alpine`. `docs/developer/server.html:223`
  (EN dito) nennt das als „Umstellung auf 18 folgt“.
- **R-1134:** Der Job `frontend-e2e` (`ci.yml:672`) läuft auf `ubuntu-24.04`, weil Playwright 1.60 auf 26.04 kein
  Chromium installierte. Das Web-Frontend nutzt seit R-1039 (#399) `@playwright/test` `^1.64.1`
  (`apps/web/package.json:23`), der Kommentar über dem Job und die Ausnahme in `docs/developer/cicd.html:42` (EN dito)
  sind damit überholt. Falsche Doku ist ein Bug.

## Ziel & Nicht-Ziele

**Ziel:** Alle CI-Services laufen auf den Hauptversionen des Stacks, `frontend-e2e` auf `ubuntu-26.04`, die Doku sagt
das.

**Nicht-Ziele:**
- Digest-Pins in `ci.yml` (heute ungepinnt, wie bisher; eigene Frage, nicht Teil der Zeilen).
- `desktop-linux` (`release.yml`) und `tauri-build-smoke` (`ci.yml`): Sie bleiben bewusst auf `ubuntu-24.04` (glibc
  des ausgelieferten Binarys).
- Die Fixtures mit `postgres:17-alpine` in `scripts/tests/restore_guard_test.sh`: Sie prüfen den Restore alter
  Sicherungen und sind Absicht.

## Betroffene Komponenten & Dateien

- `.github/workflows/ci.yml`: Services (Zeilen oben), Job `frontend-e2e` (`runs-on`, Kommentar).
- `docs/developer/cicd.html:42`, `docs/en/developer/cicd.html:42`: die Ausnahme für `frontend-e2e`.
- `docs/developer/server.html:223`, `docs/en/developer/server.html:223`: CI-Postgres.
- `changelog.d/ci-6.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

- Docker Hub `redis:8-alpine`, `postgres:18-alpine` (dieselben Hauptversionen wie `docker-compose.yml`).
- GitHub-Runner `ubuntu-26.04`; Playwright unterstützt 26.04 ab 1.61 (Notiz R-1039). Beweis ist der PR-Lauf des Jobs
  `frontend-e2e` selbst.

## Trade-offs & Alternativen

Services ohne Digest wie bisher: Ein Digest-Pin wäre konsistenter mit `docker-compose.yml`, hieße aber Pflege bei jedem
Image-Update und ist nicht beauftragt.

## Risiken & Rollback

- Postgres 18 in der CI kann Tests rot machen, die lokal (testcontainers, schon 18) grün sind, etwa wegen Unterschieden
  im Service-Container. Beweis ist die PR-CI.
- Merger ist Kevin (`.github/workflows/`, CLAUDE.md §2).
- Rollback: Revert des Merge-Commits.

## Doku-Impact

`cicd.html` und `server.html` DE+EN (siehe oben), `changelog.d/ci-6.md` (`### Changed`).

## Offene Fragen

Keine.
