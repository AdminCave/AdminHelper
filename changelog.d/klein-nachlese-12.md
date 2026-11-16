### Fixed
- Agent: ein vom Aufrufer abgebrochener Lauf haelt die vHost-Liste nicht mehr 60 s im Cache; `RunCapped` beendet bei Frist oder Ausgabegrenze die ganze Prozessgruppe; der WordPress-Check nennt einen unzulaessigen Datenbankserver beim Namen.
- Doku: Zieladresse der vHost-Checks und Zahl der Handshakes je Domain berichtigt.
