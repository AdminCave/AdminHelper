<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-desktop-1

## Problem / Motivation
R-1156: In `apps/desktop/src-tauri/src/pty.rs` sagt der Kommentar zu `Session::killer`, der Killer sei weg, sobald auf
das Programm gewartet wurde, damit kein Signal an eine vom System weitergegebene Prozess-ID gehe. Zwischen
`child.wait()` (reapt die PID) und `killer.take()` im Wait-Thread bleibt ein kurzes Restfenster: ein gleichzeitiges
`close()` kann die schon gereapte PID noch signalisieren. Der Kommentar verschweigt das.

## Ziel & Nicht-Ziele
Ziel: der Kommentar nennt das Restfenster und warum es hingenommen wird (die Spanne umfasst nur `cleanup` und
`take()`, `kill()` und `take()` sind über dasselbe Mutex geordnet). Nicht-Ziel: Verhalten ändern oder Wait und
Wegnahme umordnen (`clone_killer()` ist vom Kind getrennt, `wait()` braucht `&mut child`).

## Betroffene Komponenten & Dateien
`apps/desktop/src-tauri/src/pty.rs` (nur Kommentar).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Die Zeile erlaubt Kommentar oder Umordnen. Empfehlung: Kommentar, weil Umordnen den Wait-Thread umbaut und das
Fenster Mikrosekunden groß ist; ein Verhaltensänderung wäre kein Zug der Klein-Session.

## Risiken & Rollback
Keine, reine Kommentaränderung; Revert des Commits.

## Doku-Impact
Keine (interner Kommentar).

## Offene Fragen
Keine.
