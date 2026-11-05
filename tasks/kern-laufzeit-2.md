<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-laufzeit-2 — Task-Ledger
Status: aktiv · Branch: feature/kern-laufzeit-2 · Review: am Ende
Spec: docs/features/kern-laufzeit-2.md (Roadmap R-1032, R-1088)
Heavy: linux-full — Redis-Image in `docker-compose.yml`; den Stack mit Redis 8 fährt der Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Redis 8 in Compose und SSE-E2E (R-1032)  [ ]
Komponente: server · Dateien: docker-compose.yml, scripts/tests/sse_push_e2e.sh, DEVELOPMENT.md, changelog.d/kern-laufzeit-2.md
Änderung: `redis:8-alpine` mit Index-Digest in `docker-compose.yml`, `redis:8-alpine` in `sse_push_e2e.sh`, Dienstliste in `DEVELOPMENT.md`. Container-Probe mit dem gepinnten Image und unserem `command`: `redis-cli ping`, `tests/test_stream_redis.py` mit `AH_TEST_REDIS_URL` gegen den Container (Summary unter `## Entscheidungen`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_healthchecks.py tests/test_rate_limit.py
Doku: DEVELOPMENT.md · changelog.d/kern-laufzeit-2.md

### T2 — Kommentar zur Image-Leg in test_release_images.py (R-1088)  [ ]
Komponente: server · Dateien: apps/server/tests/test_release_images.py
Änderung: Der Kommentar an der Assertion zum Skip-Schritt nennt die 3.15-Leg statt der 3.12-Leg (Matrix 3.14/3.15, Pull nur auf 3.14).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Testkommentar)

### T3 — Redis-Server in der Lizenztabelle (R-1032)  [ ]
Komponente: docs · Dateien: THIRD_PARTY_LICENSES.md
Änderung: Unter „Auflagen & Hinweise“ ein Abschnitt zum Redis-Server-Image (Redis 8, Lizenzwahl AGPLv3, nicht mitgeliefert, sondern beim Start gezogen). Erst nach dem Merge von `feature/kern-deps-3` und `git merge origin/main` (dieselbe Datei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: THIRD_PARTY_LICENSES.md
Task-Review: am Ende

## Entscheidungen
