<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-laufzeit-2 — Redis 8 im Stack, Kommentar-Drift im Image-Test

Zug `tasks/kern-laufzeit-2.md` mit R-1032 und R-1088 (Kevin 2026-11-02: alles auf aktuelle LTS/Stable; Kevin
2026-11-04: Redis 8 unter AGPLv3).

## Problem / Motivation

- **R-1032:** `docker-compose.yml:399` zieht `redis:7-alpine` (Digest-gepinnt). Aktuell ist Redis 8.10.3
  (`redis:8-alpine`, Index-Digest `sha256:21090af93f8324db2f0f0f4f38a7c60369d47d917e000c3423d89d2ae2883537` am
  2026-11-05, `redis-server --version` im Image: `v=8.10.3`). Dieselbe Version steht in
  `scripts/tests/sse_push_e2e.sh:63` und `DEVELOPMENT.md:894`. Redis 8 ist wahlweise unter RSALv2, SSPLv1 oder AGPLv3
  lizenziert; Kevin wählt AGPLv3, `THIRD_PARTY_LICENSES.md` nennt den Redis-Server bisher gar nicht (nur den
  Python-Client `redis`, MIT).
- **R-1088:** `apps/server/tests/test_release_images.py:464` sagt „the 3.12 leg skips the image tests“; seit
  kern-laufzeit-1 ist die Matrix 3.14/3.15 und die 3.15-Leg überspringt sie (`.github/workflows/ci.yml:40,93`).

## Ziel & Nicht-Ziele

Ziel:
- Compose und das SSE-E2E-Skript fahren Redis 8 (Compose mit Digest), die Doku nennt die Version.
- Die Lizenztabelle nennt den Redis-Server mit Kevins Lizenzwahl (AGPLv3).
- Der Kommentar in `test_release_images.py` stimmt mit der Matrix.

Nicht-Ziele:
- `.github/workflows/ci.yml:60,283` (`redis:7-alpine` als CI-Service): `ci.yml` ändert der offene PR #387
  (`feature/ci-3`), und Kevin merged Workflow-PRs. Neue Zeile im Zug `ci-4`.
- Redis-Features von 8 (Search, JSON, I/O-Threads) — wir nutzen INCR/EXPIRE/GET/DELETE und Pub/Sub.

## Betroffene Komponenten & Dateien

- server (Compose ist Server-Laufzeit): `docker-compose.yml`, `scripts/tests/sse_push_e2e.sh`, `DEVELOPMENT.md`,
  `apps/server/tests/test_release_images.py`, `changelog.d/kern-laufzeit-2.md`.
- Doku: `THIRD_PARTY_LICENSES.md` (überlappt `feature/kern-deps-3`, das kurz vor dem Merge steht: T3 baut erst
  nach `git merge origin/main` mit dessen Stand).

## Datenmodell / API / Migrationen

Keine. Redis läuft ohne Persistenz (`--save "" --appendonly no`), es gibt keine Daten zu migrieren; ein
Neustart des Containers leert Zähler und Pub/Sub wie bisher.

## Externe Integrationen

- **Redis 8.0 Release Notes** (redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/
  redisce/redisos-8.0-release-notes/): einzige als „potentially breaking“ markierte Änderung sind die
  ACL-Kategorien (`@read`/`@write` umfassen jetzt Search/JSON/…). Wir setzen keine ACLs (Default-User, internes
  Netz). Lizenz: „your choice of (a) RSALv2; or (b) SSPLv1; or (c) AGPLv3“.
- Befehle des Servers: `INCR` + `EXPIRE NX` in einer Pipeline, `GET`, `DEL` (`apps/server/app/core/rate_limit.py`),
  `PUBLISH`/`SUBSCRIBE` (`apps/server/app/modules/notifications/stream_hub.py`), `PING` (Healthcheck). Beim Bau
  mit dem gepinnten Image und unserem `command` gegenprüfen: `tests/test_stream_redis.py` gegen den Container
  (`AH_TEST_REDIS_URL`), dazu `redis-cli ping`.

## Trade-offs & Alternativen

- **Index-Digest statt Plattform-Digest:** wie bei den übrigen Images (Multi-Arch, `docker compose pull` wählt die
  Plattform). Alternative ohne Digest: driftet still.
- **AGPLv3-Hinweis nur für den Redis-Server:** die übrigen Container-Images (Postgres, VictoriaMetrics, nginx,
  frps) führt die Tabelle heute nicht; sie alle aufzunehmen ist ein eigenes Vorhaben, nicht Teil dieser Zeile.

## Risiken & Rollback

- Den echten Stack mit Redis 8 (Rate-Limit, SSE-Fan-out über Worker) prüft der Sammellauf (`Heavy: linux-full`).
- Rollback: Revert des T1-Commits; ohne Persistenz kein Datenformat-Risiko.

## Doku-Impact

`DEVELOPMENT.md` (Dienstliste), `THIRD_PARTY_LICENSES.md` (Redis-Server, AGPLv3), `changelog.d/kern-laufzeit-2.md`
(`### Changed`). `docs/` nennt keine Redis-Version (`grep -rni 'redis[ :-]*[78]' docs/`).

## Offene Fragen

Keine aus Kevins Bereich (Lizenzwahl: Kevin 2026-11-04).
