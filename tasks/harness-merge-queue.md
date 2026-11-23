# Merge über die Merge Queue — Task-Ledger
Status: aktiv · Branch: feature/harness-merge-queue · Review: am Ende
Spec: docs/features/harness-merge-queue.md (Roadmap R-1345)
Heavy: none — nur Harness-Skripte, Skill-Text und Entwickler-Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1345: queue-wait.sh wartet auf den Merge aus der Queue  [ ]
Komponente: scripts · Dateien: scripts/dev/queue-wait.sh, scripts/tests/queue_wait_test.sh, scripts/tests/run.sh
Änderung: Neues `scripts/dev/queue-wait.sh <pr>` (SPDX) fragt per `gh api graphql` `state`, `mergeCommit.oid` und `mergeQueueEntry.state` ab, alle `AH_QUEUE_POLL` Sekunden (Standard 30) bis `AH_QUEUE_TIMEOUT` (Standard 5400). `MERGED` → druckt `merged <sha>`, Exit 0; `CLOSED` oder `OPEN` ohne Queue-Eintrag → druckt den Grund, Exit 1; Zeitüberschreitung Exit 3; Bedienfehler oder gh-Fehler Exit 2. Der hermetische Test `queue_wait_test.sh` (SPDX) legt ein falsches `gh` in den PATH und prüft jeden Ausgang samt Gegenprobe (ein Ausgang, der nicht fallen kann, zählt nicht); er kommt in die Testliste von `run.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict -- queue_wait_test
Doku: → T3

### T2 — R-1345: /feature-build und CLAUDE.md reihen ein statt hineinzumergen  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, CLAUDE.md, scripts/tests/harness_consistency_test.sh
Änderung: §4.6: `origin/main` nur noch bei `mergeable: CONFLICTING` hineinmergen (Union-Prüfung `CHANGELOG.md` bleibt für diesen Fall). §4.7: nach grüner PR-CI und allen Bedingungen Sammellauf-Sperre (§5) prüfen, dann `review.sh final … && gh pr merge <n>` (reiht ein; ohne Merge-Methode, nie `--admin`, ohne `--delete-branch`), dann `queue-wait.sh <n>` als Hintergrund-Wächter; „Branch muss origin/main enthalten“, „neue CI abwarten“ und „ein Merge je CI-Zyklus“ entfallen; Exit 1 → roten Queue-Lauf lesen, flaky: einmal neu einreihen plus Roadmap-Zeile, sonst Übergabe. §4.8 nimmt die Merge-SHA aus `queue-wait.sh`. CLAUDE.md §2 „Merge“ nennt das Einreihen, §5 „nicht fertig, solange der PR in der Queue steht“. `harness_consistency_test.sh` prüft: der Skill nennt `queue-wait.sh` und nicht mehr „Merge je CI-Zyklus“.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: → T3
Abhängt von: T1

### T3 — R-1345: Entwickler-Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/harness-merge-queue.md
Änderung: Branch-Schutz und Trigger-Matrix DE+EN: die Merge Queue ist aktiv (Methode Merge, Build-Konkurrenz 2, Gruppengröße 1, Check-Timeout 60 min), `ci.yml` läuft auf `merge_group` voll und prüft `main` + PR vor dem Merge. Fragment `changelog.d/harness-merge-queue.md` (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/harness-merge-queue.md
Task-Review: am Ende

## Entscheidungen
- 2026-11-23: voller Weg statt `--kurz` — R-1345 ist ein diktiertes REF ohne Fund-Beweis (`/feature-plan` 3a).
- 2026-11-23: Kevin bestätigt die Harness-Änderung („ja, plane R-1345“), Queue seit R-1344 aktiv.
