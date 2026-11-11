<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Gesamt-Timeout für die Zertifikatserneuerung — Task-Ledger
Status: erledigt · Branch: feature/kern-ca-12 · Review: am Ende
Spec: docs/features/kern-ca-12.md (Roadmap R-1216)
Heavy: none — eine Zeitgrenze im Desktop-Backend, mit hermetischem Test; kein Stack-, Gateway-, PKI-Aussteller- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1216: maybe_renew endet nach 30 s, Lock-Wartezeit eingeschlossen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/kern-ca-12.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @128cb3145 2026-11-10T18:04:36+01:00
Review: am Ende (Branch-Review)
Änderung: `maybe_renew_with` bekommt ein Budget und legt `tokio::time::timeout` um Lock, Generationsabfrage und
Erneuerung; Ablauf → `AppError::Connection`. Test: eine Abfrage, die nie antwortet, endet mit Fehler ohne Erneuerung,
und der Lock ist danach frei.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enrollment::
Doku: docs/admin/betrieb.html + docs/en/admin/operations.html (Erneuerung nach einer Rotation) · changelog.d/kern-ca-12.md
