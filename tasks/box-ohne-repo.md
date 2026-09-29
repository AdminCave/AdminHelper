<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Box ohne Repo — was über `.git` auf der Box gesagt wird — Task-Ledger
Status: erledigt · Branch: feature/box-ohne-repo · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-09-27, übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0095
Heavy: none — zwei Kommentare und eine Doku-Stelle; kein Box-, Stack- oder Install-Pfad ändert sein Verhalten.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entscheidung Kevin, 2026-09-25 (am Gate der Probe, über die Aufsicht): **kein Box-Repo.** Die Box braucht
kein `.git`, die Evidenz kommt vom Client. R-0095 schrumpft deshalb auf die drei Stellen, die sich über
`.git` auf der Box widersprechen. `vm.py` bleibt unverändert.

### T1 — `iter.sh` und `rsync-exclude.txt` beschreiben die Box, wie sie ist  [x]
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/vm/rsync-exclude.txt
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @ef0b999a 2026-09-29T08:53:42+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Die zwei Kommentare sagen dasselbe. Die Box verlässt sich nicht auf `.git`: Aus dem Haupt-Checkout
reist ein Repo mit, aus einem Worktree eine Zeiger-Datei, die auf der Box ins Leere zeigt. `run.sh` fragt
zuerst das `git` der Box und nimmt sonst `AH_HEAD`/`AH_TREE_HASH` vom Client (`run.sh:397–405`
`evidence_field`, gesetzt von `iter.sh:59–70` `evidence_envs`). Heute sagt `iter.sh:51` „The box has no
.git (the sync carries files, not the repository)“, das ist falsch für den Haupt-Checkout.
`rsync-exclude.txt:7–8` sagt „.git stays: run.sh reads head and tree_hash from it.“, das ist falsch für
einen Worktree. Nur Kommentare, kein Code.
Beweis: main@b4802aa1 · aus einem Worktree `rsync -a --exclude-from scripts/vm/rsync-exclude.txt <worktree>/ <tmp>/` (die Argumente von `vm.py:_sync`, ohne ssh) → `<tmp>/.git` ist eine Datei mit 73 Bytes, `gitdir: <Haupt-Checkout>/.git/worktrees/<name>`, ein Pfad, den es auf der Box nicht gibt · nachgestellt am 2026-09-25 im Worktree `probe-r0095`
Semantik: Kevin 2026-09-25: „kein Box-Repo — die Box braucht kein .git, die Evidenz kommt vom Client“ · docs/features/wochenlauf-gruen.md:163–164 (feature/wochenlauf-gruen@62e7ac16), Nicht-Ziele: „Kein Umbau von `vm.py sync`, sodass ein Worktree-`.git` auf der Box benutzbar wird (Harness-Datei; die Box braucht es nicht, `iter.sh` reicht die Evidenz mit).“
Dedup-Key: bug:scripts:vm.py:worktree-git-pointer
HEAD: b4802aa1
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (Kommentare; die Doku-Stelle ist T2)

### T2 — `DEVELOPMENT.md`: Sync aus einem Worktree ohne „validiert“  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @6b790d47 2026-09-29T09:01:25+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: `DEVELOPMENT.md:1165–1166` sagt heute: „Der Sync aus Worktrees ist validiert; `.git` reist mit, die
Evidenzfelder kommen trotzdem vom Client.“ Künftig steht dort, was gilt: Aus einem Worktree reist `.git` als
Zeiger mit, der auf der Box ins Leere zeigt. Die Box braucht kein Repo; Kopf und Tree-Hash gibt `iter.sh` vom
Client mit (Entscheidung Kevin, 2026-09-25). Ein Test, der auf der Box `git` voraussetzt, gehört deshalb nicht
auf die Box (wochenlauf-gruen T1/T7).
Beweis: wie T1 (main@b4802aa1, rsync-Nachstellung); dazu der Wochenlauf 2026-09-25 aus dem Worktree `weekly-wt`: `iter_flags_test` mit leerem `AH_HEAD`/`AH_TREE_HASH` auf der Box, nachgestellt `25 passed, 2 failed` (docs/features/wochenlauf-gruen.md F1, Ursache 2)
Semantik: wie T1
Dedup-Key: bug:scripts:vm.py:worktree-git-pointer
HEAD: b4802aa1
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (die Task ist die Doku)
Abhängt von: T1

### T3 — Die vier übrigen Stellen sagen dasselbe über .git auf der Box  [x]
Komponente: scripts · Dateien: AUTONOMOUS.md, scripts/vm/tests/test_vm.py, scripts/tests/iter_flags_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @2ac58133 2026-09-29T12:53:18+02:00
Review: Review am Ende (Kurz-Ledger), Re-Review folgt
Änderung: Der Gesamt-Review über T1/T2 (Opus, request_changes) fand die alte Aussage an vier weiteren Stellen:
`AUTONOMOUS.md` („Parallel-Betrieb“: „Der Sync aus Worktrees ist validiert; `.git` reist mit …“ — DEVELOPMENT.md
verweist nach T2 genau dorthin), `test_vm.py` (Kommentar über `assert ".git" not in ours`: „.git stays: run.sh reads
head and tree_hash from it“), `iter_flags_test.sh` („A box has no .git, so …“) und der Kommentar über
`evidence_field` in `run.sh` („The evidence fields come from the CLIENT, not from the box … keeps it on purpose“ —
der Code fragt zuerst das git der Box). Alle vier sagen künftig dasselbe wie T1/T2. Nur Kommentare und Doku, kein
Verhalten. Umfang von Kevin am 2026-09-29 über die Aufsicht erweitert, mit AUTONOMOUS.md und run.sh als
Harness-Dateien.
Semantik: wie T1
Dedup-Key: bug:scripts:vm.py:worktree-git-pointer
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: AUTONOMOUS.md (die Task ist Doku)
Abhängt von: T2
