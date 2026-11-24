<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI schneller (R-1743, mit R-1725)

## Problem / Motivation
Die letzten acht `merge_group`-Läufe von `ci.yml` dauerten je 14–15 min (gemessen 2026-11-24). Den kritischen Pfad
tragen die Server-`pytest`-Shards: drei Legs (py3.14, py3.15, image lock) mit je zwei Shards, der Schritt `Run
pytest` allein 735 s je Shard (Lauf 45369587438); Setup und Dienste unter 40 s, alle übrigen Jobs höchstens 6 min.
Jeder PR zahlt das zweimal: PR-CI und Queue-Lauf. Dazu wartet die Session nach dem PR bis zur grünen PR-CI und reiht
erst dann ein (`/feature-build` §4.7). Kevin hat 2026-11-24 diktiert: beides umsetzen.

## Ziel & Nicht-Ziele
- Server-`pytest` in vier Shards je Leg (`server` und `python-lock-server`): `pytest` je Shard von ~12 auf
  ~6 min; die größte Testdatei wiegt 282 s von 1121 s (`apps/server/tests/shard_weights.toml`), bei vier Shards
  also kein Shard über ~25 % der Suite.
- Die Session reiht gleich nach `gh pr create` und den Prüfungen ein (`gh pr merge <n>` schaltet bei laufender CI
  Auto-Merge ein; die Queue übernimmt bei grüner PR-CI), gebunden an den geprüften HEAD (`--match-head-commit`,
  R-1725 a). `queue-wait.sh` erkennt rote PR-Checks bei wartendem Auto-Merge (Exit 1 statt Timeout, R-1725 b).
- Nicht-Ziel: Queue-Gruppengröße (Ruleset, Kevin), weniger Tests im Queue-Lauf.

## Betroffene Komponenten & Dateien
`.github/workflows/ci.yml` (Matrix `shard`, `PYTEST_SHARD`, Jobnamen, `SHARDS` der beiden Gate-Jobs),
`docs/developer/cicd.html` + EN, `scripts/dev/queue-wait.sh`, `scripts/tests/queue_wait_test.sh`,
`.claude/skills/feature-build/SKILL.md` §4.7, `changelog.d/ci-speed-1.md`.

## Datenmodell / API / Migrationen
Keine. Die Pflicht-Checks des Rulesets heißen wie die Gate-Jobs (`Server (pytest, py3.14|py3.15)`, `Server (pytest,
image lock)`) und bleiben unverändert; nur die Shard-Jobnamen (`… shard K/4`) ändern sich.
GitHub-GraphQL: `PullRequest.commits(last:1).nodes.commit.statusCheckRollup.state` (`SUCCESS`, `FAILURE`, `ERROR`,
`PENDING`, `EXPECTED`).

## Trade-offs & Alternativen
- Vier Shards (empfohlen) gegen sechs: über vier bremst die größte Datei (282 s), und jeder Shard kostet einen Runner
  mehr. Im öffentlichen Repo kosten Runner-Minuten nichts; parallel laufen bis zu 12 Server-Jobs je Lauf.
- Früh einreihen: eine rote PR-CI hält den PR dann mit wartendem Auto-Merge; `queue-wait.sh` meldet das, die Session
  schaltet Auto-Merge ab (`gh pr merge <n> --disable-auto`), bevor sie korrigiert.

## Risiken & Rollback
Ein Shard ohne Testdatei oder eine ungleiche Sammlung fängt der vorhandene Manifest-Abgleich (`SHARDS` muss zur
Matrix passen, `test_ci_shards.py`). Rollback: Revert.

## Doku-Impact
`docs/developer/cicd.html` DE+EN (zwei → vier Shards), Fragment `changelog.d/ci-speed-1.md`.

## Offene Fragen
Keine.
