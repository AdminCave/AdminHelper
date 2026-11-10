# Harness: `./repo` der Box beim Sync stehen lassen — Task-Ledger
Status: geplant · Branch: feature/kern-harness-5 · Review: am Ende
Spec: docs/features/kern-harness-5.md (Roadmap R-0736)
Heavy: none — nur die Exclude-Liste von vm.py sync und ihr hermetischer Test, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0736: `/repo/` in der Exclude-Liste von vm.py sync  [ ]
Komponente: scripts · Dateien: scripts/vm/rsync-exclude.txt, scripts/vm/tests/test_vm.py
Änderung: `/repo/` verankert mit Kommentar wie der `/data/`-Block eintragen; Test mit echtem rsync analog
`test_the_root_data_dir_survives_a_sync_with_delete` (Box-`repo/` bleibt, `apps/x/repo/` wird weiter gelöscht). Erst rot.
Beweis: weekly 2026-10-21-1701 main@eb976421 (rsync exited 23, Box-`repo/` root:root) · Dedup-Key: bug:vm:rsync-exclude.txt:repo
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Kommentar in der Exclude-Datei)
