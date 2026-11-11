<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-1 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-1 · Review: am Ende
Spec: docs/features/klein-nachlese-1.md (Roadmap R-1269)
Heavy: none — Kommentar und Planungsdokument
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1269: Modulkommentar in frame_ws.rs umbrechen  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs
Beweis: Branch-Review kern-rdp-8 2026-11-09 (nit) · frame_ws.rs:14
Änderung: Die Zeilen 14–16 des `//!`-Kommentars werden neu umbrochen (Z. 14 ist über 100 Zeichen lang, der Absatz bricht dort nicht um); der Wortlaut bleibt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (Kommentar)

### T2 — R-1269: Spec kern-harness-4 nennt desktop_e2e_skip_test.sh  [ ]
Komponente: scripts · Dateien: docs/features/kern-harness-4.md
Beweis: Branch-Review kern-harness-4 2026-11-09 (nit) · docs/features/kern-harness-4.md:20 · tasks/kern-harness-4.md T1 (Dateien)
Änderung: Unter „Betroffene Komponenten & Dateien“ kommt `scripts/tests/desktop_e2e_skip_test.sh` dazu.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (die Änderung selbst)
Task-Review: am Ende
