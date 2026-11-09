<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-1 — zwei flaky PTY-Tests in `pty.rs`

Zug `tasks/klein-tests-desktop-1.md` mit R-1177 und R-1182. Beide Zeilen ändern nur den Testmodul-Teil von
`apps/desktop/src-tauri/src/pty.rs`; kein offener Branch berührt die Datei (`overlap.sh`, 2026-11-09).

## Problem / Motivation

- **R-1177 (Windows):** `nothing_after` (`pty.rs:617`) erwartet sofort `Disconnected`. Nach `hand_back`/`attach`
  lässt die Registry die alte Senke fallen (`pty.rs:432`), aber was die ConPTY vorher schon in den Kanal schrieb
  (`ESC[?9001h`, `ESC[?1004h`, `ESC[6n`), wartet dort noch und wird als `Data` gelesen. Betroffen sind
  `a_window_that_is_gone_hands_its_sessions_back_to_main` und `close_all_of_a_window_leaves_the_others_running`.
- **R-1182 (Linux):** `until_exit` kehrt bei `Output::Exit` zurück; die Registry entfernt die Sitzung erst danach im
  Reader-Thread (`pty.rs:284`). `assert_eq!(registry.len(), 1)` (`pty.rs:814`) liest davor.

Beides ist ein Fehler der Testhilfen, nicht des Produktcodes: die Reihenfolge Exit → Entfernen ist gewollt.

## Ziel & Nicht-Ziele

Ziel: beide Tests deterministisch. `nothing_after` räumt `Data` ab, die vor dem Loslassen der Senke gesendet wurde,
und verlangt danach `Disconnected`; `Exit` und `Replayed` bleiben Fehler (der Test wird nicht schwächer, denn nach
dem Loslassen kann nichts Neues kommen). Die Längenprüfung wartet mit Frist, bis die Registry die Sitzung entfernt
hat (wie `until_gone`). Nicht-Ziel: Produktcode, andere Tests.

## Betroffene Komponenten & Dateien

`apps/desktop/src-tauri/src/pty.rs` (nur `mod tests`), Komponente `desktop-rs`.

## Datenmodell / API / Migrationen

Keine. Keine externen Integrationen.

## Trade-offs

Alternative: `until_ready` auf Windows bis zur Ruhe warten lassen. Das verlängert jeden Lauf und bleibt ein
Zeitfenster; das Abräumen ist exakt, weil der Kanal nach dem Loslassen nichts mehr bekommt. Empfehlung: Abräumen.

## Risiken & Rollback

Gering; Test-only, einzeln zurücknehmbar. Die Windows-Seite ist nur in CI (`rust-windows`) verifizierbar; das
Ergebnis wird im PR genannt.

## Doku-Impact

Keine.

## Offene Fragen

Keine.
