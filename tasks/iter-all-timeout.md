<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Zeitlimit der all-Ebene in iter.sh — Task-Ledger
Status: aktiv · Branch: feature/iter-all-timeout · Review: am Ende
Spec: Roadmap R-0565
Heavy: none — eine Konstante des VM-Wrappers, kein Produktcode; den Beweis liefert der nächste Sammellauf über `main` (`heavy.sh all`), der vor dem Beta ohnehin fällig ist
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

`/feature-plan --kurz R-0565` (2026-10-21), geprüft gegen origin/main@82e4a7b8: `iter.sh` gibt `run.sh all` auf der warmen Box 6000 s (`scripts/vm/iter.sh:216`, `LAYER_TMO=6000`). Die grünen Sammelläufe vom 18. bis 20. Oktober brauchten 5020–5908 s (`tasks/private/history.csv`, Zeilen `all,-`). Seit R-0431 (#239) kommt `desktop_e2e_workspaces` dazu, als Einzelschritt rund 5 min auf der warmen Box. Der Sammellauf 2026-10-21-0744 über 4868a6f6 endete deshalb `UNVERIFIED` (`vm.py: timeout … exceeded 6000s`), mitten in `desktop_e2e_workspaces`. Kevin 2026-10-21: 9000 s, als Kurz-Ledger; `scripts/vm/*` ist ein Harness-Pfad, die Änderung geht auf sein Wort. Das Limit fängt nur Hänger ab und lässt Luft für weitere Suiten; die anderen Ebenen bleiben bei 3000 s.

### T1 — iter.sh: die all-Ebene bekommt 9000 s  [ ]
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/tests/iter_flags_test.sh
Änderung: Test zuerst rot: `iter_flags_test.sh:186` erwartet für `iter.sh all --strict` `--timeout 9000 ` statt `--timeout 6000 `; der Fall für `quick` (`:180-181`, `--timeout 3000`) bleibt. Dann `scripts/vm/iter.sh:216` `all) LAYER_TMO=9000`. Der Kommentar darüber (`:212-215`) nennt heute „~42 min on a warm box“; neu: Die grünen Läufe brauchten zuletzt 84–98 min, der Sammellauf 2026-10-21 lief mit `desktop_e2e_workspaces` über 6000 s, und das Limit fängt nur Hänger ab. Keine weitere Änderung an `iter.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict -- iter_flags_test
Doku: keine (intern; kein Dokument nennt das Zeitlimit)
Beweis: origin/main@82e4a7b8 · `.ah-out/weekly/2026-10-21-0744/report.md`, Zeile 1: `UNVERIFIED (the 'all' layer could not run: vm.py: timeout: … bash scripts/tests/run.sh all --strict exceeded 6000s …)`, Schritt-Tabelle `all | - | infra | 6002`; `grep -n 'LAYER_TMO=6000' scripts/vm/iter.sh` → `216:` (erwartet nach dem Fix: 9000)
Orakel: metric — Laufzeit der `all`-Ebene (history.csv: 5020–5908 s grün, 6002 s abgebrochen)
Dedup-Key: bug:harness:iter.sh:LAYER_TMO
HEAD: 82e4a7b8
Semantik: docs/developer/cicd.html:165 — „<code>all</code> = warme Box &rarr; <code>run.sh all --strict</code>“ (EN docs/en/developer/cicd.html:162: „<code>all</code> = warm box &rarr; <code>run.sh all --strict</code>“): Der Sammellauf fährt die ganze Ebene bis zu einem Urteil; ein Abbruch durch das Zeitlimit des Wrappers ist kein Urteil über den Code.
