# Gegenprobe mit gescheitertem tauri build ist keine — Task-Ledger
Status: erledigt · Branch: feature/kern-harness-9 · Review: am Ende
Spec: Roadmap R-1667
Heavy: none — heavy.sh ist ein Wrapper; heavy_test.sh prüft ihn hermetisch mit Shims, kein Stack-/Gateway-/PKI-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1667: w2-Lauf mit `tauri build failed` macht die Gegenprobe ungültig  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @45d826073 2026-11-20T13:18:17+01:00
Review: am Ende (Branch-Review)
Änderung: `second_vm_check` wertet einen roten w2-Lauf (HEAD oder Basis), dessen Log `tauri build failed` trägt, nicht als Beleg: die Spec lief dann gegen ein altes Binary. Ergebnis `unbestaetigt` mit Grund statt `extern` oder `reg`. heavy_test.sh bekommt je einen Fall für HEAD und Basis, erst rot.
Beweis: Sammellauf 2026-11-20-0130, w2-base-desktop_e2e_connect_tunnel.log:92-116 (`failed to run tauri-build: resource path binaries/frpc-x86_64-unknown-linux-gnu doesn't exist`, `SevereServiceError: tauri build failed (1)`); Schritt als extern gemeldet, war REG R-1665
HEAD: f0c050067
Dedup-Key: bug:harness:heavy.sh:w2-base-stale-binary
Semantik: docs/developer/cicd.html:264 „`extern` — rot auf der zweiten VM *und* auf dem letzten PASS-Commit“: ein Lauf, der den Basis-Commit nicht gebaut hat, war nicht auf ihm rot
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (Zeile unbestaetigt); kein changelog.d (Harness, nicht ausgeliefert)
