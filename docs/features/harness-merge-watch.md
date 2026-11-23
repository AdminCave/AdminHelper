<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Merge-Wächter ohne Modell (R-1724)

## Problem / Motivation
Seit R-1345 reiht die Session ihren PR mit `gh pr merge <n>` in die Merge Queue ein und wartet mit `queue-wait.sh`
im Hintergrund. Fällt ein PR aus der Queue (roter `merge_group`-Lauf, Konflikt) oder wird `ci.yml` auf `main` rot,
sieht das nur die Session, die gerade wartet. Ist sie beendet oder kompaktiert, bleibt der PR liegen, und keine
andere Session merkt es. Kevin hat 2026-11-23 statt einer dauerhaften Merge-Session einen Wächter ohne Modell diktiert.

## Ziel & Nicht-Ziele
- Ziel: `scripts/dev/merge-watch.sh` prüft live (zwei `gh`-Aufrufe) die Queue auf `main`, offene PRs, deren letztes
  Queue-Ereignis ein Rauswurf ist, und den neuesten abgeschlossenen `ci.yml`-Push-Lauf auf `main`. Der SessionStart-
  Hook (`session-status.sh`) zeigt eine Zeile `Merge:` und je Befund eine `WARN:`-Zeile; jede Session sieht
  Liegengebliebenes also beim Start.
- Nicht-Ziel: der Wächter repariert nichts, reiht nicht neu ein, revertiert nicht. Zuständig bleibt das Vorhaben des
  PRs (`/feature-build` §4.7).
- Nicht-Ziel: kein Cron, kein Zustandsdatei-Speicher (siehe Trade-offs).

## Betroffene Komponenten & Dateien
`scripts/dev/merge-watch.sh` (neu), `scripts/tests/merge_watch_test.sh` (neu), `scripts/tests/run.sh` (Testliste),
`scripts/dev/hooks/session-status.sh`, `scripts/tests/session_status_test.sh`, `.claude/skills/feature-build/SKILL.md`
(§4.7: ein Satz), `DEVELOPMENT.md`, `changelog.d/harness-merge-watch.md`.

## Datenmodell / API / Migrationen
Keine. Gelesen wird die GitHub-GraphQL-API: `repository.mergeQueue(branch:"main").entries` und je offenem PR
`timelineItems(last:1, itemTypes:[ADDED_TO_MERGE_QUEUE_EVENT, REMOVED_FROM_MERGE_QUEUE_EVENT])`; ein
`RemovedFromMergeQueueEvent` mit `reason` ungleich `merged` als letztes Ereignis heißt: raus und nicht wieder
eingereiht. Live gegen PR #635 geprüft (`reason: "merged"`). Dazu `gh run list --workflow ci.yml --branch main
--event push --status completed --limit 1`.

## Trade-offs & Alternativen
- **Live im Hook statt Cron mit Zustandsdatei (empfohlen):** immer frisch, nichts in Kevins Crontab, kein
  veralteter Stand. Preis: zwei `gh`-Aufrufe mit Zeitdeckel beim Sessionstart, ohne Netz steht `?`.
- Cron alle n Minuten plus Datei: sieht auch Zwischenzustände, braucht aber Installation, Aufräumen und eine
  Altersprüfung der Datei. Der Mehrwert gegenüber dem Live-Abruf wäre nur eine Historie, die niemand liest.
- Eine dauerhafte Modell-Session: verworfen (Kosten, zweiter Akteur auf fremden Ledgern).

## Risiken & Rollback
Der Hook darf nie scheitern oder blockieren: der Wächter läuft mit `timeout`, jeder Fehler wird zu `Merge: ?`.
Rollback: Revert des PRs.

## Doku-Impact
`DEVELOPMENT.md` (Abschnitt neben `nightly.sh`), Fragment `changelog.d/harness-merge-watch.md`. `cicd.html` bleibt
unberührt (offener PR #636 ändert sie).

## Offene Fragen
Keine.
