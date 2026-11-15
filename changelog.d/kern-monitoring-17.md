### Added

- **Monitoring: Check-Status `info`:** ein Hinweis ohne Alarm. Eine Modul-Regel der Stufe `info` setzt ihn, wenn
  keine `warning`- oder `critical`-Regel haelt. Der Desktop zeigt ihn blau und zaehlt ihn in der Uebersicht als
  "Hinweis"; fuer die Ampel von Host und Gruppe zaehlt er wie `ok`. Er benachrichtigt nie; faellt ein gemeldeter
  Check von `warning`/`critical` auf `info`, geht die Entwarnung raus. `GET /status/summary` hat das Feld `info`,
  `monitor_check_status` schreibt dafuer 4. Doku: Monitoring (DE+EN).

### Changed

- **Monitoring: Modul `opnsense` Version 2:** "Update verfuegbar", ein Update mit Neustart und der
  CARP-Wartungsmodus sind jetzt `info` statt nur Werte auf der Karte.
