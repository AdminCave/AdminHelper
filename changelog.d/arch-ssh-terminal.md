### Added

- **Desktop: SSH im AdminHelper-Terminal:** Eine SSH-Verbindung oeffnet in einem Sitzungs-Tab im Fenster des
  Workspace; `ssh` laeuft dort in einer Pseudo-Konsole des Desktops (unter Windows ConPTY) mit denselben Argumenten
  wie im OS-Terminal, auch ueber den Tunnel. Mehrere Sitzungen stehen als Tabs neben der Seite; je Sitzung Suche im
  Verlauf, Schrift kleiner und groesser, Neu verbinden nach dem Ende und eine Rueckfrage vor dem Beenden einer
  laufenden Sitzung. Der Verbinden-Knopf im Inspector hat fuer SSH einen Pfeil, der die Konsole fuer diesen einen
  Start waehlt (*Im AdminHelper-Terminal*, *Im OS-Terminal*); die Statusleiste zaehlt die offenen Sitzungen.
- **Desktop: Einstellungen *Terminal*:** eine sechste Sektion mit *Konsole fuer SSH* und den Terminal-Optionen
  (Schriftgroesse, Farbschema, Cursor, Scrollback, Kopieren beim Markieren, Rechtsklick fuegt ein, Schliessen
  bestaetigen); sie gelten fuer alle Workspaces des Geraets.

### Changed

- **Desktop: SSH startet standardmaessig im AdminHelper-Terminal:** Nach dem Update oeffnen Doppelklick, Enter,
  *Verbinden* und der Schnellzugriff eine SSH-Verbindung in einem Tab statt im OS-Terminal. Zurueck zum OS-Terminal
  geht es unter *Einstellungen → Terminal → Konsole fuer SSH → OS-Terminal*.
