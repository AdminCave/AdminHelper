<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-deps-4 — Task-Ledger
Status: aktiv · Branch: feature/kern-deps-4 · Review: am Ende
Spec: docs/features/kern-deps-4.md (Roadmap R-1093)
Heavy: none — nur der Lockfile-Stand eines transitiven Pakets; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — webpki-root-certs 1.0.9 → 1.0.11 im Desktop-Lockfile (R-1093)  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock, changelog.d/kern-deps-4.md
Änderung: `cargo update -p webpki-root-certs --precise 1.0.11`; im Diff ändern sich nur Version und Prüfsumme dieses Pakets. `cargo audit` (gepinnte Version aus `audit.yml`) zeigt den Befund nicht mehr.
Beweis: audit.yml 2026-11-02, gh run 41474326724 (cargo audit desktop: webpki-root-certs 1.0.9, Solution: Upgrade to >=1.0.10) · Dedup-Key: SEC:desktop:Cargo.lock:webpki-root-certs · HEAD: 4e0d5f7e
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: changelog.d/kern-deps-4.md
