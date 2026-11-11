# reg-pty-close-all: pty-Test schließt Windows-Sitzungen erst nach ihrer Cursor-Abfrage

Roadmap: R-1217 (REG, Kevin 2026-11-10 Triage).

## Problem / Motivation

`pty::tests::close_all_of_a_window_leaves_the_others_running` (`apps/desktop/src-tauri/src/pty.rs`) ist auf
`rust-windows` rot geworden und im Rerun grün. Beleg: Lauf 42634439943, Versuch 1, Panik in `next()`
(„the session answers in time“, damals `pty.rs:557`) aus `until_exit`.

Der Test öffnet zwei Sitzungen und ruft sofort `close_all_of("main")` auf. Unter Windows schickt die
Pseudokonsole zu Beginn eine Cursor-Abfrage. Laut Kommentar im Test
`a_window_that_is_gone_hands_its_sessions_back_to_main` schließt eine Pseudokonsole nicht, wenn ein lauschender
Sink diese Abfrage nie beantwortet hat. Kommt die Abfrage erst nach dem Schließen, hilft `next()` nicht mehr: Die
Antwort trifft eine Sitzung, die schon schließt. Je nach Zeitpunkt endet die Sitzung dann nicht innerhalb von 20 s.

Im Produkt beantwortet xterm.js jede Abfrage. Der Fehler liegt also im Test, nicht in `PtyRegistry`.

## Ziel & Nicht-Ziele

- **Ziel:** Der Test wartet vor dem ersten Schließen mit `until_ready` auf beide Sitzungen, wie sein
  Geschwistertest. Danach schließt er wie bisher.
- **Nicht-Ziele:**
  - Keine Änderung an `PtyRegistry`.
  - Andere pty-Tests bleiben unverändert (R-1164 im Zug kern-terminal-5 ändert `pty.rs` danach).

## Betroffene Komponenten & Dateien

`apps/desktop/src-tauri/src/pty.rs`, nur das Testmodul.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

Windows ConPTY (Cursor-Abfrage `ESC[6n` beim Start). Das Verhalten steht schon in `pty.rs` beschrieben und ist hier
nicht neu nachgelesen.

## Trade-offs & Alternativen

Eine längere Wartezeit hätte nur das Symptom verschoben. Deshalb dieselbe Vorbereitung wie im Geschwistertest.

## Risiken & Rollback

- Linux und macOS fragen nichts ab; dort ist `until_ready` ohne Wirkung.
- Den Beweis liefern nur die Windows-Jobs der PR-CI. Lokal läuft der Test unter Linux.
- **Rollback:** Revert des Task-Commits.

## Doku-Impact

Keiner, es ändert sich nur ein Test.

## Offene Fragen

Keine.
