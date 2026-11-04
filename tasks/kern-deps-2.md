<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-2 · Review: pro Task
Spec: docs/features/kern-deps-2.md (Roadmap R-1037)
Heavy: linux-full — neue Laufzeit-Pakete in Server, Monitoring und CA-Issuer; den Stack (Gateway, mTLS, SSE über Redis) fährt der Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: Pakete auf aktuell, Lock neu (R-1037)  [x]
Komponente: server · Dateien: apps/server/requirements.in, apps/server/requirements.txt, apps/server/requirements-dev.txt, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @d3772d20 2026-11-04T08:38:44+01:00
Review: approve (.ah-out/review/kern-deps-2/T1.verdict.json)
Änderung: Böden in `requirements.in` auf das aktuelle Release (Spec-Tabelle, unmittelbar vor dem Bau neu von PyPI), Dev-Pins (hypothesis, schemathesis, pytest-alembic, testcontainers, pytest-cov) ebenso; `pytest<9.2` fällt, wenn pytest-alembic 0.13.2 unter pytest 9.2 sammelt. Lock mit `pip-compile --generate-hashes --upgrade` im `python:3.14-slim` (DEVELOPMENT.md). Code oder Snapshot nur, wo ein Release es verlangt (Spec, Datenmodell / API).
Verify: bash scripts/dev/verify.sh server --strict
Doku: → T4

### T2 — Monitoring: Pakete auf aktuell, Lock neu (R-1037)  [x]
Komponente: monitoring · Dateien: apps/monitoring/requirements.in, apps/monitoring/requirements.txt, apps/monitoring/requirements-dev.txt, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped @4498dd0b 2026-11-04T08:41:28+01:00
Review: approve (.ah-out/review/kern-deps-2/T2.verdict.json)
Änderung: Wie T1 für den Monitoring-Dienst, mit denselben Böden für die gemeinsamen Pakete.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: → T4

### T3 — CA-Issuer: Pakete auf aktuell, Lock neu (R-1037)  [ ]
Komponente: ca-issuer · Dateien: apps/ca-issuer/requirements.in, apps/ca-issuer/requirements.txt, apps/ca-issuer/requirements-dev.txt, apps/ca-issuer/tests/openapi.snapshot.json
Änderung: Wie T1 für den CA-Issuer; fastapi zieht mit Server und Monitoring gleich. Er nutzt kein async, greenlet fällt aus dem Lock.
Verify: bash scripts/dev/verify.sh ca-issuer --strict
Doku: → T4

### T4 — Doku: Lizenzliste, Entwickler-Übersicht, Changelog (R-1037)  [ ]
Komponente: scripts · Dateien: THIRD_PARTY_LICENSES.md, docs/developer/index.html, changelog.d/kern-deps-2.md
Änderung: Die Python-Tabelle in `THIRD_PARTY_LICENSES.md` auf die Versionen der neuen Locks, die fastapi-Notiz darunter auf eine gemeinsame Version. `docs/developer/index.html` nennt „SQLAlchemy 2.1“ (EN „SQLAlchemy 2“ bleibt). `changelog.d/kern-deps-2.md` (neu, SPDX) unter `### Changed`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: THIRD_PARTY_LICENSES.md · docs/developer/index.html · changelog.d/kern-deps-2.md
Abhängt von: T1, T2, T3

## Entscheidungen
- R-1038 (ruff) nicht im Zug: Harness-Pfad `scripts/vm/bootstrap_linux.sh` und `ci.yml` (Spec, Offene Fragen 1).
- `THIRD_PARTY_LICENSES.md` ändert auch `feature/kern-web-4`, in einem anderen Abschnitt (Spec, Trade-offs); der Basis-Merge vor dem PR zeigt jeden Konflikt.
