# Harness: veraltete Verweise, Toolchain-Gleichlauf, Multi-Worker-Stack, Pflicht-Checks — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-13 · Review: pro Task
Spec: docs/features/kern-harness-13.md (Roadmap R-0377, R-1419, R-1060, R-0843, R-1753)
Heavy: none — Harness-Skripte und Texte; der Stack-Abschnitt laeuft im PR-Job integration-stack, die Lockstep- und Konsistenz-Pruefungen hermetisch
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Verweise auf geloeschte Teile durch die heutigen Nachfolger ersetzen (R-0377)  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, scripts/vm/lib.sh, scripts/vm/vm.py, scripts/dev/tree-hash.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @28e0bd19e 2026-11-26T22:20:02+01:00
Review: approve (.ah-out/review/kern-harness-13/T1.verdict.json)
Änderung:
- `run.sh:169`, `:333` und `:375` (Hinweis bei unlesbarem Shared-Lock) nennen nicht mehr `runner-setup.sh`;
  `run_flags_test.sh:1379` greppt den neuen Text.
- `ledger.sh:282` und `:351` nennen `task-close.sh` statt `diff-scan`; zwei Zeilen bleiben ein Fehler, weil sie nur
  eine Angabe sein sollen. `ledger_test.sh:397` zieht mit.
- `vm/lib.sh:65–95` und `vm.py:662`, `:1781` nennen `worktree-setup.sh`/`worktree-teardown.sh` statt `lane.sh`.
- `tree-hash.sh:33` ohne `.crabbox-out`.
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test ledger_test task_close_test
Doku: keine (Kommentare und Meldungstexte des Harness)

### T2 — Toolchain-Lockstep: Box-Python folgt dem Dockerfile, Box-Go der go.mod-Toolchain (R-1419, R-1060)  [x]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, scripts/vm/bootstrap_linux.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @95b43ce84 2026-11-26T22:26:23+01:00
Review: approve (.ah-out/review/kern-harness-13/T2.verdict.json)
Änderung:
- Neue Offline-Prüfung 1d: Major.Minor des Defaults von `PY_VERSION` in `bootstrap_linux.sh` gleich dem
  `FROM python:X.Y` jedes `apps/*/Dockerfile`, das eines trägt.
- Neue Offline-Prüfung 1e: Default von `GO_VERSION` gleich der `toolchain`-Direktive von `apps/agent/go.mod`.
- `GO_VERSION` 1.27.2 → 1.27.4 mit dem SHA-256 aus go.dev/dl `?mode=json`.
- Hermetische Fälle je Drift im Test.
Verify: bash scripts/dev/verify.sh scripts --strict -- toolchain_lockstep_test
Doku: → T5

### T3 — Stack-Lauf mit zwei Workern und leerem ADMIN_PASSWORD (R-0843)  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Änderung: Neuer letzter Abschnitt nach dem Wipe. `.env` mit `ADMIN_PASSWORD=` und `WEB_CONCURRENCY=2`, dann
`down -v` und `e2e_up gateway`. Erwartet:
- zwei uvicorn-Worker;
- genau ein Setup-Banner im Server-Log;
- der Token aus der Setup-Datei legt per `/api/auth/bootstrap` den ersten Admin an;
- derselbe Token ein zweites Mal wird abgelehnt.

Den echten Stack-Lauf fährt die Session lokal, seine Summary steht im Commit-Body.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: → T5

### T4 — Pflicht-Checks des Rulesets als Liste, jeder PR-Job von ci.yml darin (R-1753)  [ ]
Komponente: scripts · Dateien: scripts/dev/required-checks.txt, scripts/tests/harness_consistency_test.sh
Änderung:
- Neue Liste `scripts/dev/required-checks.txt`: SPDX-Kopf als `#`-Kommentar, der `gh api`-Befehl, der sie erzeugt,
  ein Check-Name je Zeile.
- `harness_consistency_test.sh` leitet aus `ci.yml` die Check-Namen der PR-Jobs ab, Matrix ausgeschrieben, ohne
  `Changed paths` und Shards. Jeder muss in der Liste stehen, sonst rot mit dem Hinweis „Ruleset-Eintrag (Kevin) +
  Liste“.
- Gegenprobe: ein Job ohne Listeneintrag macht den Test rot.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: → T5

### T5 — Doku: Toolchain-Lockstep, Multi-Worker-Stack und Pflicht-Check-Liste (R-1419, R-1060, R-0843, R-1753)  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Lockstep-Absatz (Go-Patch gleich der go.mod-Toolchain statt „Patch frei“, Box-Python gleich dem
Dockerfile-Python), Stack-Test (Multi-Worker-Abschnitt) und Ruleset-Absatz (Liste und ihre Prüfung), DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html DE+EN
Task-Review: am Ende

## Entscheidungen
- Kevin 2026-11-25 (Notiz jeder Zeile): „Harness-Fund angenommen (Durchsicht)“ — deckt die Harness-Pfade dieses Zugs.
- R-1364 fährt nicht mit: der sshd-Teil ist nicht verifiziert und braucht eine OPNsense-Box (Klon am 2026-11-26
  an der Kapazität gescheitert), die rc.conf-Bereinigung einen echten Bake; verschoben nach kern-harness-14.
- Der Teil `.claude/rules/testing.md` von R-0377 ist auf main 826be48 schon behoben (kein „Stufe 12“ mehr).
- T2: die Pruefungen heissen 2d (Go) und 2e (Python), weil sie hinter 2c stehen, wo `plain_version` schon
  definiert ist. 2d verlangt Box-Go >= go.mod-`toolchain` (sonst `go`), nicht Gleichheit: nur ein Box-Go
  darunter laedt per GOTOOLCHAIN=auto nach (R-1060), ein hoeherer Patch schadet nicht. 2e prueft dazu jedes
  `python3.N` in bootstrap_linux.sh und run.sh, die R-1419 als zweite Fundstelle nennt.
