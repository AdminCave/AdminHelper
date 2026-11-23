<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Merge-Wächter ohne Modell — Task-Ledger
Status: aktiv · Branch: feature/harness-merge-watch · Review: am Ende
Spec: docs/features/harness-merge-watch.md (Roadmap R-1724)
Heavy: none — nur Harness-Skripte, SessionStart-Hook, Skill-Text und Entwickler-Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1724: merge-watch.sh meldet Queue-Rauswürfe und rotes main  [x]
Komponente: scripts · Dateien: scripts/dev/merge-watch.sh, scripts/tests/merge_watch_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dacf38cb4 2026-11-23T12:35:29+01:00
Review: am Ende (Branch-Review)
Änderung: Neues `scripts/dev/merge-watch.sh` (SPDX): ein `gh api graphql` (Queue-Einträge auf `main`, je offenem PR das letzte Queue-Ereignis) und ein `gh run list` (neuester abgeschlossener `ci.yml`-Push-Lauf auf `main`). Druckt eine Zeile `Merge: Queue <n> (#a …) · main <sha7> <conclusion>` und je Befund eine Zeile `ACTION: …` (PR raus aus der Queue mit Grund und Zeit; main rot mit Lauf-ID). Exit 0 ohne Befund, 1 mit Befund, 2 bei gh-Fehler (dann `Merge: ?`). Hermetischer Test `merge_watch_test.sh` (SPDX) mit falschem `gh`, jeder Ausgang samt Gegenprobe; in die Testliste von `run.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict -- merge_watch_test
Doku: → T3

### T2 — R-1724: AH-STATUS zeigt den Wächter, /feature-build verweist darauf  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, .claude/skills/feature-build/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @750d990f5 2026-11-23T12:39:22+01:00
Review: am Ende (Branch-Review)
Änderung: `session-status.sh` ruft `merge-watch.sh` aus seinem eigenen Checkout (wie `roadmap.py`) mit Zeitdeckel, druckt die `Merge:`-Zeile nach den `Geplant:`-Zeilen und macht jede `ACTION:`-Zeile zu `warn`; fehlt das Skript oder scheitert es, `Merge: ?`, Exit bleibt 0. `session_status_test.sh` prüft Zeile, WARN und den Fehlerfall. `/feature-build` §4.7: eine `WARN:`-Zeile des Wächters zu einem PR gehört dem Vorhaben dieses PRs (Reaktion wie bei `queue-wait.sh` Exit 1); rotes main wie §4.8.
Verify: bash scripts/dev/verify.sh scripts --strict -- session_status_test
Doku: → T3
Abhängt von: T1

### T3 — R-1724: Entwickler-Doku und CHANGELOG  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, changelog.d/harness-merge-watch.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2d284bcd0 2026-11-23T12:42:04+01:00
Review: am Ende (Branch-Review)
Änderung: `DEVELOPMENT.md` neben dem Sammellauf: was der Wächter prüft, wo seine Zeile steht, wie man ihn von Hand fährt. Fragment `changelog.d/harness-merge-watch.md` (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: DEVELOPMENT.md · changelog.d/harness-merge-watch.md
Task-Review: am Ende

### T4 — R-1724: Hook startet den Wächter parallel (Abschlussprüfung)  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh
Änderung: Fund `wichtig` der Abschlussprüfung: `timeout 8` nacheinander riss bei langsamem GitHub die 10 s des SessionStart-Hooks. Der Hook startet den Wächter gleich nach `cd "$ROOT"` per Prozess-Substitution auf fd 3 (`timeout 5`) und liest ihn in Zeile 4c; ein hängender Wächter ergibt `Merge: ?`. Nit: „main ist rot“ nennt den letzten Merge (§4.8) statt des PRs. Test: hängender Wächter → `Merge: ?`, Exit 0, unter 7 s (Gegenprobe mit `timeout 8` rot: 8 s).
Verify: bash scripts/dev/verify.sh scripts --strict -- session_status_test
Doku: keine (Verhalten wie in T3 beschrieben)
