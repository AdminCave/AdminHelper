<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-laufzeit-2 — Task-Ledger
Status: bereit · Branch: feature/kern-laufzeit-2 · Review: am Ende
Spec: docs/features/kern-laufzeit-2.md (Roadmap R-1032, R-1088)
Heavy: linux-full — Redis-Image in `docker-compose.yml`; den Stack mit Redis 8 fährt der Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Redis 8 in Compose und SSE-E2E (R-1032)  [x]
Komponente: server · Dateien: docker-compose.yml, scripts/tests/sse_push_e2e.sh, DEVELOPMENT.md, changelog.d/kern-laufzeit-2.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @95169f85 2026-11-05T06:51:50+01:00
Review: am Ende (Branch-Review)
Änderung: `redis:8-alpine` mit Index-Digest in `docker-compose.yml`, `redis:8-alpine` in `sse_push_e2e.sh`, Dienstliste in `DEVELOPMENT.md`. Container-Probe mit dem gepinnten Image und unserem `command`: `redis-cli ping`, `tests/test_stream_redis.py` mit `AH_TEST_REDIS_URL` gegen den Container (Summary unter `## Entscheidungen`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_healthchecks.py tests/test_rate_limit.py
Doku: DEVELOPMENT.md · changelog.d/kern-laufzeit-2.md

### T2 — Kommentar zur Image-Leg in test_release_images.py (R-1088)  [x]
Komponente: server · Dateien: apps/server/tests/test_release_images.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @3d3e086a 2026-11-05T06:52:10+01:00
Review: am Ende (Branch-Review)
Änderung: Der Kommentar an der Assertion zum Skip-Schritt nennt die 3.15-Leg statt der 3.12-Leg (Matrix 3.14/3.15, Pull nur auf 3.14).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Testkommentar)

### T3 — Redis-Server in der Lizenztabelle (R-1032)  [x]
Komponente: scripts · Dateien: THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @69e4d565 2026-11-05T08:20:10+01:00
Review: am Ende (Branch-Review)
Änderung: Unter „Auflagen & Hinweise“ ein Abschnitt zum Redis-Server-Image (Redis 8, Lizenzwahl AGPLv3, nicht mitgeliefert, sondern beim Start gezogen). Erst nach dem Merge von `feature/kern-deps-3` und `git merge origin/main` (dieselbe Datei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: THIRD_PARTY_LICENSES.md
Task-Review: am Ende

## Entscheidungen
- T1: Redis 8.10.3, `redis:8-alpine` mit Index-Digest (Multi-Arch wie die übrigen Images). Release Notes 8.0: einzige „potentially breaking“ Änderung sind die ACL-Kategorien; wir setzen keine ACLs. Container-Probe mit dem gepinnten Image und unserem `command`: `redis-cli ping` → PONG, `tests/test_stream_redis.py` mit `AH_TEST_REDIS_URL` gegen den Container 2 passed; `RedisBackend` (INCR + EXPIRE NX in einer Pipeline, GET, DEL) zählt 1/2/3 mit TTL 60 aus Redis selbst (der In-Memory-Fallback hätte keine TTL im Server) und ist nach `reset` 0.
