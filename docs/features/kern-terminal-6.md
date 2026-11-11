# kern-terminal-6 — Terminal-Tab: Schließen trotz unbeantworteter Cursor-Abfrage

Roadmap: R-1312 (BUG, Desktop).

## Problem
- **R-1312** (`apps/desktop/src-tauri/src/pty.rs`): Unter Windows fragt die Pseudo-Konsole (ConPTY, mit
  `PSEUDOCONSOLE_INHERIT_CURSOR`) beim Start nach der Cursor-Position (`ESC[6n`) und schließt nicht, bevor die Antwort
  da ist. Die Antwort gibt xterm.js in der App; nur wenn niemand zuhört, antwortet der Lese-Thread selbst
  (`pty.rs`, Lese-Thread: `!listening && contains(…, CURSOR_QUERY)`). Lädt die Webview neu, nachdem die Abfrage an
  eine lauschende Senke ging, aber bevor xterm.js geantwortet hat, beendet `close_all_of` das Programm, die Abfrage
  bleibt aber offen. Die Pseudo-Konsole schließt dann nicht, der Lese-Thread bekommt kein Ende, und die Sitzung
  bleibt im Registry. Die Tests umgehen das heute ausdrücklich (`until_ready` vor `close_all_of`, Kommentar R-1217).
  Der Fund stammt aus einer Prüfung und ist unter Windows noch nicht beobachtet (Kevin 2026-11-11: erst unter Windows
  verifizieren, `rust-windows` oder R-0541).

## Ziel & Nicht-Ziele
Ziel: Eine geschlossene Sitzung verlässt das Registry auch dann, wenn ihre Cursor-Abfrage an eine Senke ging, die
nicht mehr antwortet.

Nicht-Ziele: Keine Änderung an der Antwort für Sitzungen ohne Zuhörer; keine Änderung an xterm.js oder der UI;
kein Warten auf Programme, die das Ende ignorieren.

## Betroffene Komponenten & Dateien
- desktop-rs: `apps/desktop/src-tauri/src/pty.rs` (`Session`, Lese-Thread, `PtyRegistry::write`, `Session::close`,
  Tests)
- `changelog.d/kern-terminal-6.md`

## Lösung
Die Sitzung merkt sich eine Abfrage, die an eine lauschende Senke ging, und vergisst sie, sobald über
`PtyRegistry::write` eine Cursor-Antwort (`ESC[<Zeile>;<Spalte>R`) zum Programm geht. `Session::close` schreibt eine
noch offene Antwort selbst, bevor es das Programm beendet. Plattformunabhängig, damit derselbe Test unter Unix
(Programm fragt selbst, ignoriert SIGHUP und gibt die Antwort aus) und unter Windows (ConPTY fragt) läuft.

## Nachweis unter Windows
Erst der Test allein: auf einem Wegwerf-Branch per `workflow_dispatch` von `ci.yml` im Job `rust-windows`; rot
belegt den Fund, grün heißt kein Fehler unter Windows (dann die Zeile mit diesem Beleg schließen, Fix nur für die
Unix-Hälfte nicht nötig). Danach Fix und Test auf dem Feature-Branch, PR-CI `rust-windows` grün.

## Trade-offs & Alternativen
- Immer beim Schließen eine Antwort schreiben (ohne Merker): einfacher, schreibt aber einem laufenden Programm, das
  das Ende ignoriert (etwa SIGHUP unter Unix), eine fremde Eingabe. Verworfen.
- Abfrage nach einer Frist selbst beantworten: ändert das Verhalten laufender Sitzungen. Verworfen.

## Risiken & Rollback
Ein Programm, dessen Abfrage xterm.js mit einer Antwort in mehreren Schreibvorgängen beantwortet, bekäme beim
Schließen eine zweite Antwort; es wird dabei beendet. Rollback: Revert des Task-Commits.

## Doku-Impact
Keine Seite beschreibt die Cursor-Abfrage; nur `changelog.d/kern-terminal-6.md` (`### Fixed`).

## Offene Fragen
Keine.
