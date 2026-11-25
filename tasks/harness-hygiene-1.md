<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Hygiene 1 — Task-Ledger
Status: aktiv · Branch: feature/harness-hygiene-1 · Review: pro Task
Spec: docs/features/harness-hygiene-1.md (Roadmap R-1721, R-1722, R-1723, R-1768, R-0479, R-0481, R-0593, R-1265, R-0914, R-1024, R-1347, R-1408, R-1680, R-1683)
Heavy: linux-full — T5 ändert `scripts/backup.sh`, dessen Beweis `backup-restore` (echter Stack) nur der Sammellauf fährt; alles andere ist hermetisch
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-11-25: Harness-Funde aus der Durchsicht angenommen; „kümmere du dich um alles“.

### T1 — roadmap.py stats: Verlauf in einem Lauf lesen (R-1721)  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dc75af869 2026-11-25T15:29:51+01:00
Review: approve (.ah-out/review/harness-hygiene-1/T1.verdict.json)
Änderung: `waits()` (`scripts/dev/roadmap.py:1247`) liest die Statuswechsel aus einem einzigen `git log -p`-Lauf
statt einem `git show` je Commit; dieselben Werte wie bisher (Test vergleicht beide auf einem Fixture-Repo). Die
tote Kennzahl `kevin-min/PR` (`:1283-1285`) fällt weg.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T10

### T2 — worktree-teardown.sh: gemergt gegen origin/main, Reste fremder UID (R-1722, R-1768)  [x]
Komponente: scripts · Dateien: scripts/dev/worktree-teardown.sh, scripts/tests/worktree_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d69863adf 2026-11-25T15:38:41+01:00
Review: approve (.ah-out/review/harness-hygiene-1/T2.verdict.json)
Änderung: `dropdb` und Venv vor `git worktree remove`; Reste unter dem Worktree, die dem Nutzer nicht gehören, räumt
ein Wegwerf-Container (ohne Docker: klarer Fehlertext). Der Branch gilt als gemergt, wenn er nach `git fetch`
Vorfahr von `origin/main` ist (dann `git branch -D`). Tests: ein Branch, der nur in `origin/main` gemergt ist, geht;
ein Lauf mit fremd-eigenem Rest (Fixture per Stub) räumt DB und Venv trotzdem.
Beweis: worktree-teardown.sh:110-117 (branch -d gegen lokalen main); ops-16 Teardown 2026-11-24
Verify: bash scripts/dev/verify.sh scripts --strict -- worktree_setup_test
Doku: → T10

### T3 — nightly.sh: alte Berichte aufräumen (R-1723)  [x]
Komponente: scripts · Dateien: scripts/tests/nightly.sh, scripts/tests/nightly_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @cca9acfdb 2026-11-25T15:44:23+01:00
Review: approve (.ah-out/review/harness-hygiene-1/T3.verdict.json)
Änderung: Vor jedem Start löscht `nightly.sh` unter `.ah-out/weekly/` alle Läufe außer den 30 neuesten; Läufe, deren
erste Berichtszeile nicht `PASS` ist, bleiben 90 Tage. Gelöscht wird nur mit vollem Pfad je Verzeichnis, nie ein
laufender (ohne `report.md`-Urteil und jünger als ein Tag).
Verify: bash scripts/dev/verify.sh scripts --strict -- nightly_test
Doku: → T10

### T4 — review-risk.txt: fehlende Risikopfade (R-0479, R-0481, R-0593, R-1265)  [x]
Komponente: scripts · Dateien: scripts/dev/review-risk.txt, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fc99e31db 2026-11-25T15:52:44+01:00
Review: approve (.ah-out/review/harness-hygiene-1/T4.verdict.json)
Änderung: Aufnehmen: `apps/server/app/core/config.py`, `scripts/agent-install.sh`,
`apps/monitoring/app/checkers/http.py`, `apps/agent/internal/probe/`, `apps/agent/internal/discovery/`,
`apps/agent/internal/credentials/`; ein Test je Pfad, dass `review.sh risk` ihn als Risikopfad meldet.
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: keine (die Liste ist ihre eigene Doku)

### T5 — backup.sh/diagnostics.sh: Zwischendatei-Handling härten (R-0914)  [x]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/diagnostics.sh, scripts/tests/diagnostics_test.sh, scripts/tests/restore_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @91351c68e 2026-11-25T16:10:27+01:00
Review: approve (.ah-out/review/harness-hygiene-1/T5.verdict.json)
Änderung: Nach dem Plan in `tasks/private/` (Roadmap-Zeile R-0914); das Archiv entsteht und heißt wie bisher.
`security` prüft die Task.
Verify: bash scripts/dev/verify.sh scripts --strict -- diagnostics_test
Doku: → T10 (CHANGELOG neutral)

### T6 — run.sh: Test-Venvs nach dem Lock (R-1024)  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @140832048 2026-11-25T16:57:49+01:00
Review: approve (.ah-out/review/harness-hygiene-1/T6.verdict.json)
Änderung: Die Python-Schritte installieren `requirements-dev.txt` mit dem Lock der Komponente als Constraint, so dass
die Venv die Lock-Versionen trägt (Belegt: `~/.cache/ah-venv` sqlalchemy 2.1.9, Lock 2.1.8). Ob pip den gehashten
Lock als Constraint nimmt, wird zuerst belegt; sonst ein hash-freier Auszug in `AH_OUT_DIR`.
Beweis: `~/.cache/ah-venv/bin/python -c 'import sqlalchemy;print(sqlalchemy.__version__)'` → 2.1.9; `apps/server/requirements.txt:883` 2.1.8
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: → T10

### T7 — heavy_test.sh: Negativ-Assertionen ohne pipefail-Falle, Fall rot + Fuzz (R-1347)  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy_test.sh, .claude/skills/test/SKILL.md, .claude/skills/feature-build/SKILL.md
Änderung: Negativ-Assertionen auf `report_of` (`heavy_test.sh:478` und gleichartige) erst in eine Variable, dann
prüfen; ein Fall „roter Schritt plus Fuzz-Fund im Teil-Detail“; die zwei überlangen Skill-Zeilen umbrechen. Der
CLAUDE.md-Teil des Nits fährt nicht mit.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (Test und Zeilenumbruch)

### T8 — cache_settings.sh: compose-build-Formen (R-1408)  [ ]
Komponente: scripts · Dateien: .github/scripts/cache_settings.sh, .github/scripts/cache_settings_test.sh
Änderung: `docker compose -f x.yml build`, `docker compose --file …  build` und `docker-compose build` in einem
`run:`-Schritt sind Verstöße wie `docker build`; der Kopfkommentar (`cache_settings.sh:24`) nennt sie; Test je Form.
Verify: bash scripts/dev/verify.sh scripts --strict -- .github/scripts/cache_settings_test
Doku: keine (Kopfkommentar)

### T9 — windows_update_set_test: de_DE ohne installierte Locale (R-1683)  [ ]
Komponente: scripts · Dateien: scripts/tests/windows_update_set_test.sh, .claude/rules/release.md
Änderung: Fehlt `de_DE.UTF-8`, erzeugt der Test sie per `localedef` in ein eigenes Verzeichnis (`LOCPATH`) und prüft
das Verhalten echt; nur ohne `localedef` bleibt die statische Prüfung. Dazu R-1680: `release.md:66` nennt
`ReleasePublicKey` (`apps/agent/internal/selfupdate/minisign.go:22`) als dritte Pin-Stelle.
Verify: bash scripts/dev/verify.sh scripts --strict -- windows_update_set_test
Doku: diese Task (release.md)

### T10 — Doku: DEVELOPMENT.md und Changelog  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, changelog.d/harness-hygiene-1.md
Änderung: DEVELOPMENT.md: Teardown (gemergt gegen `origin/main`, Reste), Aufräumen der Berichte, `stats` ohne
`kevin-min`. Changelog-Fragment (ae/oe/ue) unter Entwickler-Werkzeuge, Backup/Diagnose neutral.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- T1: Engpass war das Parsen (12 216 Fassungen × 10 ms), nicht `git show`; `waits()` liest jetzt nur die `+|`-Zeilen eines `git log -p -U0`. Gegenprobe auf dem privaten Repo: 400,4 s → 16,5 s, gleiche Werte bis auf drei Übergänge aus 67 alten Fassungen mit doppelter ID (R-0047, R-0084), deren Flip-Flop die alte Fassung zählte.
- T2: Ob der Worktree gehen darf, entscheidet `git status --porcelain` vor allem anderen (ein unsauberer behält auch seine DB); fremd-eigene Pfade findet `find ! -user $(id -u) -prune`, entfernt je Pfad `docker run --rm --network none … alpine rm -rf` (Muster `uninstall.sh`); ohne Remote prüft das Skript weiter gegen den lokalen `main`. Gegenprobe: alte Fassung 5 failed (alpha-Meldung, rho, sigma, tau).
- T3: Aufräumen läuft in `run` direkt vor dem tmux-Start (nicht im Dry-Run, nicht bei übersprungener Nacht); Alter aus dem Verzeichnisnamen, „läuft noch“ = kein Urteil und mtime jünger als ein Tag. Gegenprobe: alte Fassung 2 failed.
- T4: Die drei Agent-Pakete als eigener Block (Proben und Discovery laufen auf dem Host, credentials trägt Geheimnisse), `config.py` bei Auth, `checkers/http.py` bei SSRF, `agent-install.sh` bei Install. Gegenprobe: alte Liste 6 failed.
- T5: Das Archiv entsteht in einem eigenen 0700-Verzeichnis im Ausgabeordner (`mktemp -d`), das Skript arbeitet darin über relative Namen und prüft Eigentümer, Mode und Inode vor dem Schreiben; kein zusätzliches `chmod 600` (Mode kommt von `mktemp`, die fd-Prüfung verlangt 600, auch unter Default-ACL). Das leere Verzeichnis räumt der EXIT-trap per `rmdir` nur über den Namen. Gegenprobe: alter Stand restore_guard 3 failed, diagnostics 6 Meldungen; je ein Mutant (ohne Inode-Vergleich, Zwischendatei über den Namen) rot. Runde 2 (security, wichtig): ein setgid-Ausgabeordner vererbt das Bit, `2700` gilt als eigen; das Bit bleibt, damit das Archiv wie bisher die Gruppe des Ordners trägt (Gegenprobe ohne `2700`: je 1 rot).
- T6: pip nimmt den gehashten Lock nicht als Constraint („Constraints cannot have extras“, Hashes ebenso); `pip_dev` in `run.sh` zieht je Komponente einen `name==version`-Auszug nach `AH_OUT_DIR/constraints-<komp>.txt` und installiert `requirements-dev.txt -c` darauf, ein leerer Auszug bricht ab. Beleg: Worktree-Venv danach sqlalchemy 2.1.8 = Lock. Gegenprobe: alter `run.sh` 2 failed, Mutant „Extras im Auszug“ 1 failed.
