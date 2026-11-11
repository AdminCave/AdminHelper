<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-1 — Spec

## Problem
- **R-1269:** Zwei der Review-Nits aus den Branch-Reviews vom 2026-11-09 sind eindeutig: der Modulkommentar in
  `apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs` (Z. 14) bricht mitten im Absatz nicht um und ist über 100 Zeichen
  lang, und die Spec `docs/features/kern-harness-4.md` nennt unter „Betroffene Komponenten & Dateien“ nicht
  `scripts/tests/desktop_e2e_skip_test.sh`, das die Task T1 des Ledgers ändert.
- Die übrigen drei Nits sind ohne den Wortlaut der Reviews nicht zuordenbar; sie stehen als eigene Zeile (R-1334).

## Ziel / Nicht-Ziele
Kommentar umbrechen, Dateiliste der Spec ergänzen. Kein Verhalten ändert sich; Nicht-Ziel: die drei unklaren Nits raten.

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/rdp_embedded/frame_ws.rs` (nur Kommentar), `docs/features/kern-harness-4.md`.

## Datenmodell / API / Integrationen
Keine.

## Trade-offs
Keine.

## Risiken & Rollback
Keine; zwei Commits.

## Doku-Impact
Keine (interner Kommentar, Planungsdokument), kein Changelog-Fragment.
