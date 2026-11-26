### Changed

- **Test-Boxen:** Das Aufwaermen beim Backen einer Vorlage baut nur noch die Caches (Go, Cargo, npm) und faehrt die reinen Testschritte nicht mehr; es lief zuvor in seine Zeitgrenze, bevor Cargo und npm dran waren. `vm.py` bricht einen stehenden `rsync` nach 300 s ohne Daten ab, statt den Lauf zu blockieren.
- **Test-Boxen:** `scripts/vm/bootstrap_linux.sh` laedt alles ueber einen Helfer mit Wiederholung, Verbindungsgrenze und Abbruch bei stehendem Transfer; `pip3`, `apt` und `cargo install` wiederholen ebenfalls. Ein einzelner Aussetzer eines Paketservers bricht keine Box mehr ab.
- **Images:** Die Dockerfiles von Server, CA-Issuer und Monitoring wiederholen `apt-get`, `pip install` und `npm ci` bei einem Netzfehler; Paketstand und Hash-Pruefung sind unveraendert.
