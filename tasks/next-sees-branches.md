<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `roadmap.py next` sieht Ledger auf Branches (R-0099) — Task-Ledger
Status: bereit · Branch: harness/next-sees-branches · Commit-Granularität: pro Task · Review: am Ende (feature-review; Harness-Pfad roadmap.py ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-27 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/next-sees-branches.md (Roadmap R-0099)
Heavy: none — nur scripts/dev (Stdlib-Python, hermetische Fixtures); kein Stack-, Gateway-, PKI- oder Install-Pfad, keine DB, keine VM.
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Bau nur interaktiv (roadmap.py und der Skill sind Harness-Pfade). Vor Stufe 7 mergen. Tests an roadmap.py nur
über `--file` und eigene Fixtures, nie gegen `tasks/private/ROADMAP.md`. `verify.sh scripts` reicht keine
Argumente an `dev-pytest` durch; jedes Verify fährt den ganzen scripts-Key.

### T1 — `components_of` liest das Ledger aus Baum und allen Refs  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @32b1f39c 2026-09-29T07:15:32+02:00
Review: am Ende (Kurz-Ledger)
Änderung: `components_of` (roadmap.py:814–834) vereinigt die `Komponente:`-Zeilen aus dem Baum (wie heute) und
aus jedem `refs/heads/*` und `refs/remotes/*` (ohne symbolisches `HEAD`), das den Pfad trägt: ein
`git -C ROOT grep` über alle Bäume mit `--literal-pathspecs`, aufgerufen mit einer Umgebung ohne `GIT_DIR`,
`GIT_WORK_TREE`, `GIT_INDEX_FILE`. Ohne git oder ohne Repo nur der Baum, wie heute. Die ROOT-Sperre für absolute
Pfade und der `(`-Filter gelten auch für Ref-Inhalte. Docstring :49–52 nachziehen. Tests (neu, Fixture-Repo über
den git-Helfer der Testdatei): nur lokaler Branch → `{"scripts"}`; nur `refs/remotes/origin/feature/x` →
gefunden; zwei Refs mit verschiedener Komponente → Vereinigung; `next --exclude-components scripts` auf einer Zeile,
deren Ledger nur am Branch liegt → Exit 1.
Beweis: origin/main@70e91718 · `python3 -B scripts/dev/roadmap.py --file <(Zeile R-0095, Ledger tasks/box-ohne-repo.md) --today 2026-09-27 next --exclude-components scripts` → `R-0095 BUG Box ohne Repo (tasks/box-ohne-repo.md)`, Exit 0; erwartet Exit 1 (`git show feature/box-ohne-repo:tasks/box-ohne-repo.md` trägt `Komponente: scripts`)
Dedup-Key: bug:scripts:roadmap.py:components_of
HEAD: 70e91718
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (`next`: wo das Ledger gesucht wird, der Aufrufer fetcht vorher)

### T2 — fail-closed: ein genanntes Ledger, das nirgends liegt, zählt als Konflikt  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @0afee83a 2026-09-29T07:25:24+02:00
Review: am Ende (Kurz-Ledger)
Änderung: Nur mit `--exclude-components` wird eine Zeile übersprungen, deren repo-relativer Ledger-Pfad
(`tasks/….md`) weder im Baum noch auf einem Ref liegt; dazu auf stderr `next: R-nnnn skipped — ledger <pfad> not
found in the tree or on any branch (git fetch?)`. Ohne Ausschlussliste, bei `—`, bei Slug-Formen und bei
absoluten Pfaden außerhalb bleibt alles wie heute; bestehende Tests bleiben unverändert. Tests (neu): fehlendes
Ledger plus Ausschluss → übersprungen, stderr nennt ID und Pfad; ohne Ausschluss → geliefert; war es die einzige
Zeile → Exit 1.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (`next`, fail-closed)
Abhängt von: T1

### T3 — Gate-Text: `next` sieht Branch-Ledger  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @d0656f57 2026-09-29T07:33:06+02:00
Review: am Ende (Kurz-Ledger)
Änderung: Der Satz „`next --exclude-components` sieht es dort noch nicht (R-0099)" (feature-plan/SKILL.md, §4,
um :203–205) wird ersetzt: `next` sieht Ledger auf lokalen und Remote-Branches (nach `git fetch`), ein nirgends
gefundenes Ledger gilt als Konflikt; `git show <branch>:tasks/<slug>.md` bleibt für die Prüfung von Hand
(Contract-Dateien). `skill_consistency_test.sh` muss danach grün bleiben.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (der Skill ist selbst Prozess-Doku)
Abhängt von: T2
