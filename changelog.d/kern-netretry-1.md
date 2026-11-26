### Changed

- **Test-Boxen:** Das Aufwaermen beim Backen einer Vorlage baut nur noch die Caches (Go, Cargo, npm) und faehrt die reinen Testschritte nicht mehr; es lief zuvor in seine Zeitgrenze, bevor Cargo und npm dran waren. `vm.py` bricht einen stehenden `rsync` nach 300 s ohne Daten ab, statt den Lauf zu blockieren.
