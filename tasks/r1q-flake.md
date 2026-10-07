<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ledger_loop_test: der Fall r1q flakt in der CI (R-0200) — Task-Ledger
Status: bereit · Branch: harness/r1q-flake · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-07 (kleines Fund-Paket aus der von Kevin am 2026-10-06 angenommenen Zeile R-0200; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0200 (Kurz-Ledger ohne Spec)
Heavy: none — ein hermetischer Harness-Test und gegebenenfalls `scripts/dev/ledger-loop.sh`; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-07 von der Aufsicht (adminhelper-ac). Kevin hat R-0200 am 2026-10-06 angenommen (damals „in 7b“); 7b wird
zur Stufe „Team“ umgeschnitten, und der Fall macht `main` inzwischen zum zweiten Mal rot. Deshalb ein eigenes
Kleinpaket. Bau interaktiv (Harness-Pfad). Zeilenangaben main@a50bdf4e.

### T1 — r1q: Diagnose in der Fehlermeldung, Ursache finden und beheben (R-0200)  [x]
Komponente: scripts · Dateien: scripts/tests/ledger_loop_test.sh, scripts/dev/ledger-loop.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @78e59f06 2026-10-07T11:26:25+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Der Fall `r1q` (`ledger_loop_test.sh:736–740`) meldet bei Rot nur `result r1q` und damit „- —“: Der Loop
endete, bevor er r1q in `state.json` eintrug, und keine Lane entstand. Zuerst nennt der `bad`-Zweig `rc` und die letzten
Zeilen von `$OUT` (ohne Geheimnisse; die Fixture hat keine). Dasselbe gilt für die übrigen `bad`-Zweige, die nur `result`
oder `stopped` ausgeben, soweit sie `rc`/`OUT` zur Hand haben. Dann die Ursache: den Test unter Last wiederholen
(etwa 20 Läufe, parallel zu einer CPU-Last wie `stress`/`yes`, oder mit `nice`/`taskset` auf einen Kern), bis r1q
rot wird, und anhand von `rc`/`OUT` erklären. Verdächtig, nicht belegt: eine Sperre (`loop.lock`), die ein Kind des
vorherigen Falls `stl` noch hält, oder ein Preflight-Schritt mit Zeitgrenze. Ist die Ursache belegt: an der Wurzel
beheben (Test oder Loop) und einen Fall ergänzen, der genau diese Bedingung erzwingt und ohne den Fix rot ist. Lässt
sie sich in vertretbarer Zeit nicht reproduzieren: nur die Diagnose committen und `[~]` mit dem Satz „Diagnose
eingebaut, nächster roter Lauf zeigt die Ursache“.
Beweis: CI auf `main`, Job „Ops scripts (shellcheck + update test)“: Lauf 37401861552 Versuch 1 (Merge #84) und Lauf
37595378501 Versuch 1 (Merge #92) je `FAIL r1q: - —`, `ledger_loop_test: 108 passed, 1 failed`; die Reruns waren grün;
lokal 6 von 6 Läufen grün (2026-10-06).
Dedup-Key: bug:scripts:ledger_loop_test.sh:r1q-flaky
HEAD: a50bdf4e
Semantik: CLAUDE.md §6: „ein erst roter, dann grüner Test ist `flaky`, nicht PASS“ — ein Test auf `main`, der flakt,
ist ein Fehler, den wir beheben, nicht wegwiederholen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
