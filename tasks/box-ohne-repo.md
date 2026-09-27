<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Box ohne Repo — was über `.git` auf der Box gesagt wird — Task-Ledger
Status: freigegeben · Branch: feature/box-ohne-repo · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-09-27, übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0095
Heavy: none — zwei Kommentare und eine Doku-Stelle; kein Box-, Stack- oder Install-Pfad ändert sein Verhalten.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entscheidung Kevin, 2026-09-25 (am Gate der Probe, über die Aufsicht): **kein Box-Repo.** Die Box braucht
kein `.git`, die Evidenz kommt vom Client. R-0095 schrumpft deshalb auf die drei Stellen, die sich über
`.git` auf der Box widersprechen. `vm.py` bleibt unverändert.

### T1 — `iter.sh` und `rsync-exclude.txt` beschreiben die Box, wie sie ist  [ ]
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/vm/rsync-exclude.txt
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

### T2 — `DEVELOPMENT.md`: Sync aus einem Worktree ohne „validiert“  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md
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
