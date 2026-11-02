<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-laufzeit-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-laufzeit-1 · Review: pro Task
Spec: docs/features/kern-laufzeit-1.md (Roadmap R-1029, R-1030, R-1031, R-1033)
Heavy: linux-full — Basis-Images von Gateway, Server, Monitoring, CA-Issuer und das VictoriaMetrics-Image in `docker-compose.yml`; der Sammellauf baut und startet den Stack
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@8c4fe2f5`. Merge durch Kevin (`.github/workflows/` im Diff), dazu Anpassung der Pflicht-Checks im Ruleset (T2). Versionen und Digests vor dem Bauen neu auflösen (`docker buildx imagetools inspect`).

### T1 — Gateway auf nginx 1.30-alpine (R-1029)  [x]
Komponente: server · Dateien: apps/gateway/Dockerfile, changelog.d/kern-laufzeit-1.md, .github/workflows/ci.yml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @033df0c4 2026-11-02T11:44:55+01:00
Review: approve (.ah-out/review/kern-laufzeit-1/T1.verdict.json)
Änderung: `FROM nginx:1.30.6-alpine@sha256:<Digest>` statt 1.29 (`apps/gateway/Dockerfile:1`). Vorher in den nginx-CHANGES 1.29 → 1.30 prüfen, ob eine Direktive der Gateway-Konfiguration betroffen ist, und `nginx -t` gegen das neue Image fahren.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py tests/test_images_exec_only.py
Doku: changelog.d/kern-laufzeit-1.md

### T2 — Python 3.14 in Images, Locks und CI (R-1030)  [x]
Komponente: scripts · Dateien: Dockerfile, apps/monitoring/Dockerfile, apps/ca-issuer/Dockerfile, apps/server/requirements.txt, apps/monitoring/requirements.txt, apps/ca-issuer/requirements.txt, .github/workflows/ci.yml, .github/workflows/audit.yml, ruff.toml, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/kern-laufzeit-1.md, apps/server/tests/test_release_images.py, apps/server/tests/test_images_exec_only.py, docs/developer/index.html
Evidenz: run.sh[quick] scripts server: 10 passed, 0 failed, 8 skipped @692889b1 2026-11-02T14:58:59+01:00
Review: approve (.ah-out/review/kern-laufzeit-1/T2.verdict.json)
Änderung: `FROM python:3.14-slim@sha256:<Digest>` in den drei Dockerfiles; gehashte Locks unter 3.14 neu erzeugen (pip-compile wie im Lock-Kopf, in einem `python:3.14-slim`-Container); `ci.yml`-Matrix `["3.14", "3.15"]`, Lock-Jobs und Einzel-Python-Stellen auf 3.14, die 3.13-gebundenen Schritte auf 3.14; `audit.yml` auf 3.14; `ruff.toml` `target-version` auf die neue Untergrenze, sofern es keinen Lint-Umbau erzwingt (sonst bleibt es, Entscheidung im Ledger). `test_lock_pins.py` hält Images und Lock-Jobs gleich. Mehr als acht Dateien: Images, Locks und CI hängen über `test_lock_pins.py` zusammen und sind nur gemeinsam grün.
Verify: bash scripts/dev/verify.sh scripts server --strict
Doku: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html (Matrix-Namen, Python-Versionen), changelog.d/kern-laufzeit-1.md

### T3 — Node 26 LTS (R-1031)  [ ]
Komponente: web · Dateien: Dockerfile, .github/workflows/ci.yml, .github/workflows/release.yml, .github/workflows/audit.yml, apps/web/package.json, apps/web/package-lock.json, apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, DEVELOPMENT.md, changelog.d/kern-laufzeit-1.md
Änderung: `FROM node:26-alpine@sha256:<Digest>` im `frontend-build`, `node-version: "26"` an allen Stellen, `@types/node` auf ^26 in Web und Desktop-UI samt Lockfiles, `DEVELOPMENT.md` „Node.js 26+“. Abhängt von T2 nur über `Dockerfile` und `ci.yml` (Reihenfolge).
Verify: bash scripts/dev/verify.sh web desktop-ui --strict
Doku: DEVELOPMENT.md, changelog.d/kern-laufzeit-1.md
Abhängt von: T2

### T4 — VictoriaMetrics v1.155.0 (R-1033)  [ ]
Komponente: monitoring · Dateien: docker-compose.yml, changelog.d/kern-laufzeit-1.md
Änderung: `victoriametrics/victoria-metrics:v1.155.0@sha256:<Digest>` (`docker-compose.yml:573`). Vorher die Update-Notes im VictoriaMetrics-CHANGELOG von v1.145 bis v1.155 auf Flags und Datenformat prüfen, die unser Compose-Kommando nutzt; Befund unter `## Entscheidungen`.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: changelog.d/kern-laufzeit-1.md

## Entscheidungen
- 2026-11-02 Plan: R-1031 ändert `DEVELOPMENT.md:759`. Der offene PR #363 (feature/plan-worktree) ändert dort nur die Hunks bei 602 und 1342, deshalb fährt R-1031 trotz der Überlappung auf Dateiebene mit.
- 2026-11-02 Plan: R-1033 geht auf Community-Stable v1.155.0, weil es LTS nur für Enterprise gibt (Spec).
- 2026-11-02 T2: `ruff.toml` `target-version` geht auf `py313`, nicht `py314`. Unter `py314` formatiert ruff 23 Dateien auf `except A, B:` ohne Klammern um (PEP 758), und das läuft unter dem 3.13 der Dev-Box (Debian 13) für die Skripte unter `scripts/` nicht. `py313` ist ohne Umbau grün (check und format).
- 2026-11-02 T2: Die Locks sind unter python:3.14-slim aus dem bestehenden Lock neu kompiliert. Die Pins und Hashes bleiben gleich, es ändern sich nur Kopf und via-Kommentare.
- 2026-11-02 T2: Die volle Leg mit Image-Pull und „No test skipped“ ist 3.14 (die Python-Version der Images). `test_release_images.py` und `test_images_exec_only.py` (Interpreterpfad im Image) ziehen deshalb mit. Verify ist auf `scripts server` erweitert.
