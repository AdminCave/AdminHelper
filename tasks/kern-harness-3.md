# Harness: exakter Schrittname, Einstufung nicht ansprechbarer Schritte, Probelauf ohne Abräumen — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-3 · Review: am Ende
Spec: docs/features/kern-harness-3.md (Roadmap R-1148, R-1206, R-1153)
Heavy: none — nur Harness-Skripte mit hermetischen Tests (run_flags_test, heavy_test, vm.py pytest); kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1148: Ein exakter Schrittname gewinnt bei --step  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @df2a5b20c 2026-11-09T17:13:50+01:00
Review: am Ende (Branch-Review)
Änderung: Der Trockenlauf von `--step` nimmt bei mehreren Teilstring-Treffern den einen, dessen Name gleich dem gesuchten ist, und der echte Lauf fährt dann nur ihn (`want_step` vergleicht exakt); ohne exakten Treffer bleibt es `ambiguous step`, Exit 2. Test in run_flags_test: ein Name, der Präfix eines anderen Schritts ist, fährt genau einen Schritt; ein Teilstring über mehrere bleibt mehrdeutig.
Beweis: feature/arch-ssh-terminal@49b3538b · `iter.sh all --strict --step desktop_e2e_connect` → `ambiguous step: 'desktop_e2e_connect' matches 2 steps`, Exit 2
Dedup-Key: bug:scripts:scripts/tests/run.sh:want_step
HEAD: 001151564
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (Zeile `--step`)

### T2 — R-1206: heavy.sh stuft einen nicht ansprechbaren Schritt nicht als rot ein  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5ed86de93 2026-11-09T17:25:36+01:00
Review: am Ende (Branch-Review)
Änderung: Endet ein Retry (`classify_red_step`) mit `ambiguous step`/`unknown step` im Log, ist der Schritt `infra` (Detail „step not addressable“), ohne weitere Retries; endet ein Lauf der Zweit-VM (`second_vm_check`, HEAD oder Basis) so, bleibt der Kandidat `unbestaetigt`, nie `extern` oder `reg`. Tests in heavy_test mit gestubbtem iter.sh für Retry, HEAD-Lauf und Basis-Lauf.
Beweis: main@d5092bc55 · weekly 2026-11-09 `.ah-out/weekly/2026-11-09-0959/retry-desktop_e2e_connect-1.log` (`ambiguous step`), Report-Zeile `desktop_e2e_connect | extern`
Dedup-Key: bug:scripts:scripts/tests/heavy.sh:retry_step
HEAD: 001151564
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (Einstufung `infra` und `unbestaetigt`)

### T3 — R-1153: vm.py reap --dry-run sweept die Lane nicht  [ ]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py
Änderung: `auto_reap` läuft nicht nach `reap --dry-run`; jedes andere Verb sweept wie bisher. Test: `reap --dry-run` ruft `reap_lane` nur im Probemodus, der Sweep bleibt aus; `reap` ohne `--dry-run` sweept weiter.
Beweis: main@a3645c00 · `vm.py reap --all --dry-run` aus dem Haupt-Checkout meldete `reaped expired` für eine abgelaufene Box der Lane main (2026-11-05)
Dedup-Key: bug:scripts:vm.py:auto_reap-dry-run
HEAD: 001151564
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_vm_test
Doku: keine (der Probelauf ist als nebenwirkungsfrei dokumentiert; das Verhalten folgt jetzt der Doku)

## Entscheidungen
- R-1157 wandert in `tasks/kern-harness-4.md`: braucht einen Box-Beweis des GUI-Schritts (Heavy `linux-full`), und solange der Sammellauf rot ist, merged die Session kein `linux-full`-Vorhaben.
- T3 verifiziert über `-- lib_vm_test`: der Schritt `vm.py pytest` (scripts/vm/tests) läuft im Block `scripts` unabhängig von der Testauswahl nach `--`.
