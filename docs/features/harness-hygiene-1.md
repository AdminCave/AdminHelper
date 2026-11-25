<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Hygiene 1 — Spec

Zug aus der Durchsicht der zurückgestellten Roadmap-Zeilen (Kevin 2026-11-25: Harness-Funde angenommen) und der
Umschau vom 2026-11-23. Zeilen: R-1721, R-1722, R-1723, R-1768, R-0479, R-0481, R-0593, R-1265, R-0914, R-1024,
R-1347, R-1408, R-1680, R-1683.

## Problem je Zeile

- **R-1721** `roadmap.py stats` braucht über zwei Minuten: `waits()` (`scripts/dev/roadmap.py:1247`) fährt je Commit
  des privaten Repos ein `git show` und parst die ganze Datei. Die Kennzahl `kevin-min/PR` liefert nie einen Wert.
- **R-1722 / R-1768** `worktree-teardown.sh` prüft „gemergt“ mit `git branch -d` gegen den lokalen `main` (bleibt
  nach einem Queue-Merge liegen, bis der Haupt-Checkout vorspult), und `git worktree remove` scheitert an Resten,
  die ein Stack-Test als Container-UID angelegt hat (`./data`); danach überspringt ein zweiter Lauf `dropdb` und
  das Venv.
- **R-1723** `.ah-out/weekly` wächst ohne Aufräumen (68 Läufe, 570 MB am 2026-11-23).
- **R-0479, R-0481, R-0593, R-1265** `scripts/dev/review-risk.txt` fehlen Pfade mit Sicherheitswirkung:
  `apps/server/app/core/config.py`, `scripts/agent-install.sh`, `apps/monitoring/app/checkers/http.py`,
  `apps/agent/internal/{probe,discovery,credentials}/`.
- **R-0914** `backup.sh`/`diagnostics.sh`: Umgang mit der Zwischendatei im Ausgabeordner härten (Einzelheiten nur
  in `tasks/private/`).
- **R-1024** Die Test-Venvs installieren aus `requirements.in` (Untergrenzen) statt aus dem Lock: am 2026-11-25
  `~/.cache/ah-venv` mit sqlalchemy 2.1.9, Lock (`apps/server/requirements.txt`) 2.1.8.
- **R-1347** `heavy_test.sh:478`: Negativ-Assertion `report_of | grep -q … && bad` unter `pipefail`; kein Fall für
  rot plus Fuzz-Fund im Teil-Detail; zwei Skill-Zeilen über der Zeilenlänge. Der CLAUDE.md-Teil des Nits fährt
  nicht mit (CLAUDE.md-Änderungen nur auf Kevins ausdrückliches Ja).
- **R-1408** `.github/scripts/cache_settings.sh` erkennt `docker compose -f x.yml build` und `docker-compose build`
  nicht; der Kopfkommentar nennt die Formen nicht.
- **R-1680** `.claude/rules/release.md:66` nennt als minisign-Pin-Stellen nur `install.sh` und `update.sh`, nicht
  `ReleasePublicKey` in `apps/agent/internal/selfupdate/minisign.go:22`.
- **R-1683** `windows_update_set_test.sh:71` prüft das Locale-Verhalten ohne installiertes `de_DE.UTF-8` nur
  statisch.

## Ziel & Nicht-Ziele

Jede Zeile wird an ihrer Wurzel behoben, mit einem Test, der vorher rot ist (wo es um Verhalten geht). Nicht-Ziele:
`ci.yml` (Merger Kevin; die CI-Jobs bleiben unverändert, nur der Schemathesis-Job pinnt mit, weil er `run.sh` fährt), CLAUDE.md, neue Kennzahlen in `stats`.

## Entscheidungen der Session

- `stats`: den Verlauf mit einem einzigen `git log -p`-Lauf lesen statt je Commit; `kevin-min/PR` fällt weg (keine
  Zeile trägt Minuten, die Spalte bleibt).
- Teardown: „gemergt“ heißt Vorfahr von `origin/main` nach `git fetch`; `dropdb` und Venv vor `worktree remove`;
  fremd-eigene Reste unter dem Worktree räumt ein Wegwerf-Container (nur mit Docker, sonst ein klarer Fehlertext).
  Die 67 schon gemergten lokalen Branches löscht die Session nach dem Merge einmal mit dem neuen Skript.
- Aufräumen der Berichte: `nightly.sh` behält die 30 neuesten Läufe und darüber hinaus nicht-PASS-Läufe der letzten
  90 Tage; `history.csv` bleibt die Langzeit-Quelle.
- Venvs: `run.sh` installiert mit dem Lock als Constraint (Hashes entfernt, wenn pip sie im Constraint nicht nimmt —
  beim Bau zu belegen).

## Betroffene Dateien

`scripts/dev/roadmap.py`, `scripts/dev/tests/test_roadmap.py`, `scripts/dev/worktree-teardown.sh`,
`scripts/tests/worktree_setup_test.sh`, `scripts/tests/nightly.sh`, `scripts/tests/nightly_test.sh`,
`scripts/dev/review-risk.txt`, `scripts/tests/review_scripts_test.sh`, `scripts/backup.sh`, `scripts/diagnostics.sh`,
`scripts/tests/diagnostics_test.sh`, `scripts/tests/run.sh`, `scripts/tests/heavy_test.sh`,
`.claude/skills/test/SKILL.md`, `.claude/skills/feature-build/SKILL.md`, `.github/scripts/cache_settings.sh`,
`.github/scripts/cache_settings_test.sh`, `.claude/rules/release.md`, `scripts/tests/windows_update_set_test.sh`,
`DEVELOPMENT.md`, `changelog.d/harness-hygiene-1.md`.

## Datenmodell / API / Migrationen

Keine.

## Risiken & Rollback

Teardown und `run.sh` sind Werkzeuge jeder Session: ein Fehler dort hält alle auf. Jede Task ist einzeln
zurücknehmbar (`git revert`). `backup.sh` ist ein Restore-Pfad: `backup-restore` (echter Stack) fährt der Sammellauf (`Heavy: linux-full`).

## Doku-Impact

DEVELOPMENT.md (Teardown, Aufräumen der Berichte, `stats`), `changelog.d/harness-hygiene-1.md` (Entwickler-Werkzeuge,
Betrieb: Backup/Diagnose ohne Verhaltensänderung).

## Offene Fragen

Keine.
