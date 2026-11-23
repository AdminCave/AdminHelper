<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Merge über die Merge Queue (R-1345)

## Problem / Motivation
Seit 2026-11-23 verlangt das Ruleset von `main` eine Merge Queue (R-1344): Merge-Methode `MERGE`, Build-Konkurrenz 2,
Gruppengröße 1, Check-Timeout 60 min, `ALLGREEN`. `ci.yml` läuft schon auf `merge_group`. Der Merge-Ablauf in
`/feature-build` §4.6–§4.7 baut aber noch die Queue von Hand nach: vor dem Merge `origin/main` hineinmergen, pushen,
einen zweiten vollen CI-Zyklus abwarten, ein Merge je CI-Zyklus (`.claude/skills/feature-build/SKILL.md:116`,
`:124`–`:128`). Das kostet nach der Workflow-Analyse vom 2026-11-11 (V6) rund 60 Zusatzzyklen je Woche. Die Queue prüft
die Kombination `main` + PR jetzt selbst vor dem Merge.

`gh pr merge` reiht bei verlangter Queue ein, statt zu mergen (`gh pr merge --help`, gh 2.103.3: „If required checks
have passed, the pull request will be added to the merge queue“). Der Befehl kehrt also zurück, bevor der PR gemergt
ist; §4.8 braucht danach den Merge-Commit.

## Ziel & Nicht-Ziele
Ziel:
- `/feature-build` §4.6–§4.8: kein Hineinmergen von `origin/main` mehr, außer GitHub meldet einen Konflikt
  (`mergeable: CONFLICTING`); kein „ein Merge je CI-Zyklus“. Nach grüner PR-CI und allen Bedingungen reiht
  `review.sh final … && gh pr merge <n>` ein (ohne Merge-Methode, nie `--admin`). Die Sammellauf-Sperre (§5) prüft die
  Session vor dem Einreihen.
- Ein Helfer `scripts/dev/queue-wait.sh <pr>` wartet ohne Modell auf das Ende: gemergt (Merge-SHA, Exit 0), aus der
  Queue gefallen oder geschlossen (Exit 1), Zeitüberschreitung (Exit 3). Danach §4.8 wie bisher mit dem Lauf des
  Merge-Commits.
- CLAUDE.md §2 (Merge) und §5 (nicht „fertig“, solange der PR in der Queue steht) nennen die Queue.
- Doku `docs/developer/cicd.html` DE+EN: Queue ist aktiv, mit ihren Einstellungen.

Nicht-Ziele:
- Gruppengröße > 1 (V6 Stufe 5) und schlanke PR-CI (V3): eigene Zeilen, Kevins Bereich (Ruleset, Workflow).
- Keine Änderung an `ci.yml`, am Ruleset oder an `review.sh final`.
- Kevins Merge-Vorbehalt (`.github/workflows/`, `install.sh`, `agent-install.sh`, `update.sh`, fremde PRs) bleibt.

## Betroffene Komponenten & Dateien
- `.claude/skills/feature-build/SKILL.md` §4.6–§4.8 (Zeilen 116–135)
- `CLAUDE.md` §2 „Merge“ (Zeilen 43–47), §5 letzter Punkt (Zeile 96)
- neu `scripts/dev/queue-wait.sh` (SPDX), neu `scripts/tests/queue_wait_test.sh` (SPDX), Eintrag in der Testliste
  `scripts/tests/run.sh:703`
- `scripts/tests/harness_consistency_test.sh` (Block um Zeile 163: der Skill nennt `queue-wait.sh` und kein „Merge je
  CI-Zyklus“ mehr)
- `docs/developer/cicd.html:78`, `:96`, `docs/en/developer/cicd.html:76`, `:94`; `changelog.d/harness-merge-queue.md`

## Datenmodell / API / Migrationen
Keine. Keine Vertrags-Drift.

## Externe Integrationen
- GitHub GraphQL: `pullRequest { state mergeCommit { oid } mergeQueueEntry { state position } }`. Live geprüft am
  2026-11-23 gegen dieses Repo (Felder vorhanden, `mergeQueue(branch:"main").configuration` zeigt `MERGE`, 2, 3600 s).
  Doku: https://docs.github.com/en/graphql/reference/objects#mergequeueentry
- gh CLI `gh pr merge` mit Queue: `gh pr merge --help` (gh 2.103.3), wörtlich oben zitiert.
- Managing a merge queue: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue

## Trade-offs & Alternativen
- **Warten per Helfer-Skript (gewählt)** statt einer Schleife im Skill-Text: das Erkennen „aus der Queue gefallen“
  (offen, kein `mergeQueueEntry`) ist eine Fallunterscheidung, die getestet sein soll; das Skript läuft als
  Hintergrund-Wächter ohne Modellaufrufe (CLAUDE.md §5).
- **`gh pr merge --auto`** zum früheren Einreihen: verworfen, die Bedingungen aus §4.7 (CI im ersten Anlauf grün,
  Urteile) prüft die Session vorher; `--auto` würde einen PR mit später rotem Lauf trotzdem mergen lassen.
- **Hineinmergen ganz streichen**: bleibt nur bei Konflikt, weil die Queue einen konfliktbehafteten PR nicht annimmt.

## Risiken & Rollback
- Ein Wackler wirft einen PR aus der Queue: `queue-wait.sh` meldet Exit 1, die Session reiht nach Prüfung des roten
  Laufs einmal neu ein (flaky ⇒ Rerun plus Roadmap-Zeile, CLAUDE.md §2), sonst Übergabe.
- Rollback: Kevin nimmt die Regel aus dem Ruleset, der Skill-Text geht per Revert zurück.

## Doku-Impact
`docs/developer/cicd.html` DE+EN: Branch-Schutz und Trigger-Matrix nennen die aktive Queue; CHANGELOG-Fragment.

## Offene Fragen
Keine. R-1345 ist von Kevin diktiert (2026-11-11), die Harness-Änderung hat er am 2026-11-23 bestätigt.
