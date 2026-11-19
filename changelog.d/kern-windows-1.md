### Added

- **Agent Windows: Tunnel laufen jetzt auch unter Windows:** der Agent-Dienst startet frpc als Kindprozess, prueft
  vorher den gepinnten SHA-256 von `frpc.exe` und startet frpc nach einem Ende neu. Jedes Release enthaelt dafuer
  `frpc-windows-x86_64.exe`; die Datei gehoert beim Install neben den Agent.
- **Agent Windows: `service uninstall --purge`** loescht zusaetzlich Programm- und Datenordner (nur Windows, nur
  Ordner im Besitz von Administratoren oder SYSTEM).
- **Monitoring Windows:** der Agent meldet den Starttyp der Dienste (gestoppte Autostart-Dienste erscheinen als
  inaktiv) und, ueber `w32tm`, ob die Uhr synchron ist.

### Changed

- **Agent Windows: eigener Programmordner `%ProgramFiles%\AdminHelper Agent`** mit Schreibrecht nur fuer SYSTEM und
  Administratoren; `service install` ist zugleich das Update (stoppen, ersetzen, starten) und zieht eine Installation
  aus dem alten Ordner `%ProgramFiles%\AdminHelper` um.
- **Desktop:** der Befehl fuer Windows-Zugangsdaten im Monitoring nennt den neuen Programmordner.

### Fixed

- **Agent:** der Tunnel-Abgleich richtet das Datenverzeichnis ein, bevor er daraus liest; Tunnel-Befehle ausserhalb
  des Windows-Dienstes melden einen Fehler statt eines Erfolgs.
