# kern-terminal-5 — Run-Verzeichnis beim App-Ende, Windows-Downloadnamen, Ende der RDP-Sitzung im Verlauf

Roadmap: R-1164, R-1272, R-1273 (alle BUG, Desktop).

## Problem
- **R-1164** (`apps/desktop/src-tauri/src/pty.rs`): Ein Ansible-Lauf im Tab (`terminal_open_ansible`) bekommt ein
  Run-Verzeichnis mit Inventory und Playbook (`Spawn::cleanup`). Entfernt wird es nur im Wait-Thread nach
  `child.wait()` (`pty.rs:239–244`). Beim Beenden der App ruft `main.rs:327` (`RunEvent::Exit`) `close_all()` auf. Das
  schickt das Ende an das Programm, wartet aber nicht darauf. Der Prozess endet, bevor der Wait-Thread aufräumt, und
  das Verzeichnis bleibt im Temp-Verzeichnis liegen. Dasselbe gilt, wenn das Programm SIGHUP ignoriert.
- **R-1272** (`apps/desktop/src-tauri/src/sftp.rs:229`, `suggested_name`): Der Name im Speichern-Dialog eines
  Downloads ersetzt heute nur `\`, `:`, Steuer- und Bidi-Zeichen. Unter Windows sind aber auch `<>"/|?*` verboten,
  ebenso ein Leerzeichen oder Punkt am Ende und die reservierten Gerätenamen (auch mit Endung, etwa `NUL.txt`).
  Ein solcher Vorschlag macht den Dialog fehlerhaft oder führt auf ein Gerät.
- **R-1273** (`apps/desktop/ui/src/lib/stores/connectFlow.ts`, `connectRdpInTab`): RDP im Tab beginnt einen Eintrag im
  Sitzungsverlauf (`markConnectionUsed`), beendet ihn aber nie. SSH im Tab macht das seit R-1159 (`connectEmbedded`,
  `watchEnd`).

## Ziel & Nicht-Ziele
Ziel:
- Nach `RunEvent::Exit` ist kein Run-Verzeichnis eines Tabs mehr da.
- Unter Windows bietet der Speichern-Dialog nur Namen an, die Windows zulässt.
- Der Verlaufseintrag eines RDP-Tabs endet einmal, sobald der Tab `disconnected` zeigt oder geschlossen wird, wie
  bei SSH.

Nicht-Ziele:
- Kein Warten auf Programme, die das Ende ignorieren: Die App endet trotzdem, nur ihr Verzeichnis geht.
- Unter Linux und macOS bleibt der Namensvorschlag unverändert. Dort sind diese Zeichen erlaubt, und der Dialog
  nimmt sie an.
- Keine Änderung am Verlauf für RDP über den OS-Client (`rdp-exit`, `markRdpExit`).

## Betroffene Komponenten & Dateien
- T1: desktop-rs, `pty.rs` (`Session`, Wait-Thread, neue Methode `shutdown`), `main.rs` (Exit-Hook)
- T2: desktop-rs, `sftp.rs` (`suggested_name`, neue reine Funktion für Windows-Namen)
- T3: desktop-ui, `stores/terminals.ts` (`openRdp` mit `onEnd`), `stores/connectFlow.ts` (`connectRdpInTab`), Test
  in `stores/terminals.test.ts` bzw. `connectFlow`-Test
- Doku jeweils in der Task: `docs/developer/desktop.html` und `docs/en/developer/desktop.html`, dazu
  `changelog.d/kern-terminal-5.md`

## Datenmodell / API / Migrationen
Keine. Kein Tauri-Command, kein Wire-Format ändert sich.

## Externe Integrationen
Windows-Namensregeln laut Microsoft, „Naming Files, Paths, and Namespaces“
(https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file), gelesen am 2026-11-11:
- Verbotene Zeichen: `< > : " / \ | ? *`, NUL und 1–31.
- Reserviert: CON, PRN, AUX, NUL, COM1–9, COM¹²³, LPT1–9, LPT¹²³, „also … followed immediately by an extension“.
- Ein Name darf nicht mit Leerzeichen oder Punkt enden.

## Trade-offs & Alternativen
- **R-1164:** `shutdown(grace)` ruft `close_all()` auf, wartet bis `grace` darauf, dass die Wait-Threads der Sitzungen
  mit Run-Verzeichnis fertig sind, und entfernt dann selbst, was noch da ist. Die Wartezeit ist nötig, weil Windows
  Dateien nicht löscht, die ein laufendes Programm offen hält.
  - Alternative: Verzeichnis sofort ohne Warten löschen. Unter Windows scheitert das, solange `ansible-playbook`
    läuft.
  - Empfehlung: kurze Wartezeit (2 s) beim App-Ende.
- **R-1272:** Eine reine Funktion macht den Namen windows-tauglich und ist auf allen Plattformen getestet. Angewandt
  wird sie nur unter `cfg(windows)`.
  - Reservierte Namen erhalten ein `_` vor der Endung (`NUL.txt` → `NUL_.txt`).
  - Am Ende werden Punkte und Leerzeichen abgeschnitten; bleibt nichts übrig, heißt die Datei `download`.
- **R-1273:** `openRdp` nimmt wie `openTerminal` ein optionales `onEnd` (`watchEnd`). Wie bei SSH endet der Eintrag
  beim ersten `disconnected`; ein späteres Neuverbinden im selben Tab beginnt keinen neuen Eintrag. Das ist die
  Semantik von R-1159 (`docs/developer/desktop.html`: „den beendet `connectEmbedded` einmal, sobald der Tab fehlt
  oder `disconnected` zeigt“).

## Risiken & Rollback
- Gering, je Task einzeln revertierbar.
- T1 verlängert das Beenden der App um höchstens die Wartezeit, und nur, solange ein Tab mit Run-Verzeichnis läuft.
- Die Windows-Pfade von T1 und T2 prüft der CI-Job rust-windows.

## Doku-Impact
`docs/developer/desktop.html` DE+EN:
- Ansible-Zeile: das Run-Verzeichnis geht auch beim App-Ende.
- SFTP-Absatz: die Windows-Regeln von `suggested_name`.
- Verbindungsschritte: RDP im Tab beendet den Verlaufseintrag wie SSH.

Dazu `changelog.d/kern-terminal-5.md`.

## Offene Fragen
Keine.
