<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# REF-Bündel scripts (R-0046, R-0057, R-0090, R-0083, R-0096, R-0100) — Task-Ledger
Status: aktiv · Branch: harness/ref-scripts · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-27 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0046, R-0057, R-0090, R-0083, R-0096, R-0100
Heavy: none — run.sh, iter.sh und heavy.sh ändern sich nur als Test-Werkzeug; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den geänderten venv-Pfad auf der Box (T4) prüft der nächste Wochenlauf, bis dahin der Gleichheitstest in T4.
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: harness-stufe-5c — beide ändern scripts/tests/run.sh, heavy.sh, heavy_test.sh und DEVELOPMENT.md

Geplant 2026-09-27 von der Aufsicht (adminhelper-ac) auf Kevins Wort (`/feature-plan --bundle scripts`). Keine der
sechs Zeilen ist erledigt oder hinfällig; R-0057 ist zur Hälfte erledigt (lane-isolation), bei R-0046 ist der
crabbox-Teil weggefallen. Bau nur interaktiv (fünf Tasks ändern Harness-Pfade), keine Lane. Nach dem 5c-Merge
alle Zeilenangaben frisch greppen. `Dateien:` kommagetrennt; kein `|| true`/`set +e` in hinzugefügten Zeilen.
Jedes Verify fährt den ganzen scripts-Key (etwa 3 min) und damit `heavy_test`; tritt dort der bekannte Flake
R-0103 auf (`FAIL log: … roadmap: add R-0018`), gilt „flaky (R-0103)", neu fahren, kein PASS.

Von der Aufsicht gewählt (am Gate genannt): venv-Default `$HOME/.cache/ah-venv` (der Pfad von `.devenv.sh`,
`runner-setup.sh` und dem Lane-Schema) statt eines dritten Namens; ruff-Gate über ganz `scripts`, die Schritt-Id
`ruff-vm` bleibt (sonst vier Stellen in `AH_REQUIRED`, eine davon in der `.devenv.sh` des Hosts); der Guard in
R-0046 bewacht ci.yml gegen bootstrap plus den Boden in requirements-dev (der Runner-Pin bleibt bei R-0074);
R-0100 schreibt die mechanisch bekannten Felder (Option B); R-0083 schaltet in task-close um. Nicht im Bündel,
obwohl REF/scripts: R-0080 (Python-Sperre, Voraussetzung für Stufe 7) und R-0044 (doc-smoke-Env-Namen).

### T1 — R-0046: ruff-Pins im Lockstep-Guard  [x]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @c8841a28 2026-09-29T07:00:29+02:00
Review: approve (opus), 3 nits erledigt
Änderung: Eine dritte Prüfung in `toolchain-lockstep.sh`, **vor** dem Proxy-Abruf: die Version aus `ci.yml`
(`pip install ruff==X`, :101) muss gleich dem Default von `RUFF_VERSION` in `scripts/vm/bootstrap_linux.sh:31` sein,
und der Boden in `apps/server/requirements-dev.txt` (`ruff>=…`) darf X nicht übersteigen. Bei Drift Exit 1 mit
`::error::`, das die Stellen nennt. In `ci.yml` (Schritt um :564) nur den Schrittnamen erweitern. Test: `fixture()`
schreibt zusätzlich bootstrap und requirements-dev; neue Fälle: Drift ci ≠ bootstrap → rc 1 mit Wortlaut; dieselbe
Drift bei `FAKE_RC=6` bleibt rc 1, nicht 75; fehlender Pin → rc 1. Vorher rot, weil das Skript ruff nicht prüft.
Orakel: contract — Paritätstest, rot bei einer einzelnen Mutation der Pin-Version
Metrik: bewachte ruff-Pin-Paare 0 → 1, dazu der Boden
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Kopfkommentar des Skripts)

### T2 — R-0096: der scripts-Block fährt alle Skripte und meldet die Summe  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @428db12c 2026-09-29T07:14:49+02:00
Review: approve (opus)
Änderung: `scripts_block` (run.sh:548–578) merkt sich Name und rc jedes roten Skripts und läuft weiter; am Ende eine
Zeile `N of M failed: a b`, danach `return 1` (ein Fehler zählt mehr als ein Skip). Die Zeile
`     <t>: FAILED (rc=N)` (:562) bleibt, weil `heavy.sh` `first_marker` die erste FAIL-Zeile liest. Kommentar
:527–530 anpassen. Test: `run_flags_test.sh:449–453` („block: stops at the first failure") umkehren, etwa mit
`blockpass blockfail blockpass blockfail2`: alle vier laufen, beide Namen erscheinen, rc 1. Vorher rot, weil nur
zwei laufen.
Dedup-Key: ref:scripts:run.sh:scripts-block-stops
Orakel: property — bei k roten Skripten laufen alle
Metrik: Skripte, die nach dem ersten roten noch laufen: 0 → alle (Wochenlauf 2026-09-25: 19 von 31 liefen nicht)
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — R-0090: ruff-Gate über ganz `scripts/` in run.sh und CI  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, .github/workflows/ci.yml, DEVELOPMENT.md, ruff.toml
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @9ccfe24e 2026-09-29T07:33:15+02:00
Review: approve (opus), nit erledigt
Änderung: Der Schritt `ruff-vm` (run.sh:505–514) lintet und formatiert-prüft `scripts` statt `scripts/vm`; die Id
bleibt, der Name wird „ruff check (scripts)" bzw. „ruff format check (scripts)". `ci.yml:103` und `:105` gleich
ziehen. Die veralteten Kommentare `DEVELOPMENT.md:124–127` und `ruff.toml:5–9` (CI decke nur server und monitoring
ab) korrigieren. Test: ein ruff-Stub protokolliert seine argv; `lint --only scripts` muss `scripts` abdecken; eine
Paritätsprüfung vergleicht die Pfade in `ci.yml` mit denen des Schritts; die Stepnamen-Referenzen im Test
nachziehen. Vorher rot. Mit ruff 0.15.20 ist `scripts` heute sauber (`All checks passed!`, 7 Dateien formatiert).
Orakel: analyzer — ruff 0.15.20
Metrik: ruff 0.15.20: Python-Dateien unter scripts/ im Gate 3/7 → 7/7
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (ruff-Abschnitt :124 ff.)
Abhängt von: T2

### T4 — R-0057: `AH_VENV`-Default von /tmp nach ~/.cache  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/vm/iter.sh, scripts/tests/sse_push_e2e.sh, DEVELOPMENT.md
Änderung: Default `$HOME/.cache/ah-venv` in `run.sh:139` (mit HOME-Fallback über `getent` wie an anderer Stelle in
run.sh, wegen `set -u`), derselbe Default in `iter.sh:127` (VENVPRE) und in `sse_push_e2e.sh:30` als
`${VENV:-${AH_VENV:-…}}`. Kommentare run.sh:134, iter.sh:124, sse_push_e2e.sh:19 und `DEVELOPMENT.md:996`
nachziehen. `lane.sh` bleibt unverändert (der Lane-Teil ist erledigt). Test in `run_flags_test.sh` (der Test
exportiert `AH_VENV` global, der neue Fall leert es lokal): `AH_VENV` ungesetzt, `HOME=$WORK/home`, ein python3-Stub
protokolliert `-m venv <pfad>`, der Pfad liegt unter `$WORK/home/.cache`; dazu prüft der Test, dass die drei
Defaults gleich sind. Vorher rot.
Orakel: contract
Metrik: Code-Defaults unter /tmp: 3 → 0
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Default-Pfad des Test-Venvs)
Abhängt von: T3

### T5 — R-0100: das REG-Ledger aus heavy.sh in der Form von `--kurz`  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, tasks/README.md
Änderung: `write_reg_ledger` (heavy.sh:635 ff.) schreibt den Kopf mit `Review: am Ende`, `Modell: Opus`,
`Heavy: linux-full — …` und der DoD-Zeile, in der Task die Zeilen `Beweis:`, `Dedup-Key: reg:<slug>` und
`HEAD: <commit>`. Die Zeile `Roadmap:` bleibt (feature-build liest sie). Der Kommentar heavy.sh:633–634 sagt künftig:
ein Entwurf, den `/feature-plan --kurz` um Komponente, Verify und Semantik ergänzt. `tasks/README.md` (Absatz zu
`reg-*.md`) nachziehen. Test: Fall 4h in `heavy_test.sh` prüft zusätzlich `^Heavy: linux-full`,
`^Dedup-Key: reg:web-vitest`, `^HEAD:` und `Review: am Ende`, dazu ein sauberes `ledger.sh lint`. Vorher rot.
Dedup-Key: ref:scripts:heavy.sh:write_reg_ledger-shape
Orakel: contract
Metrik: fehlende Kopf- und Beweisfelder im REG-Ledger: 6 → 0
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (reg-*.md)

### T6 — R-0083: `task-close` setzt nach der letzten Task `bereit`  [ ]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/tests/task_close_test.sh, .claude/skills/feature-build/SKILL.md, DEVELOPMENT.md
Änderung: Nach `ledger.sh mark-done` (task-close.sh:290–291): steht der Kopf auf `aktiv` und ist keine Task mehr
`[ ]`, dann `ledger.sh status "$LEDGER" bereit`; das Stagen danach nimmt es in denselben Commit. `feature-build/SKILL.md`
Abschluss-Schritt 1: ein Hand-Commit ist nur noch nötig, wenn die letzte Task per mark-skip oder `[?]` zuging. Die
Schritt-Nummern bleiben (skill_consistency_test liest Schritt 5). `DEVELOPMENT.md` (Task schließen, :371 ff.): ein
Satz. Test: zweites Fixture-Ledger mit genau einer offenen Task; danach trägt `HEAD:tasks/one.md` `Status: bereit`
und lintet sauber; Gegenfälle: ist noch eine Task offen, bleibt `aktiv`; `geplant` bleibt unberührt. Vorher rot.
Beweis: origin/main@70e91718 · `git show 2528c88d:tasks/harness-stufe-5b.md` → `Status: aktiv`, kein `[ ]` mehr offen (Invariante tasks/README.md verletzt)
Orakel: property — Invariante „kein `[ ]` offen ⇒ nicht `aktiv`" (tasks/README.md)
Metrik: Commits mit `aktiv` ohne offene Task in den letzten 60 Commits dreier Ledger: 10 → 0; der Hand-Commit „ready" je Bau entfällt
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Task schließen)
