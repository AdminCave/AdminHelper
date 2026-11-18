### Changed

- **Monitoring-Katalog: Checks einer Instanz und Port-Alternativen am Host:** ein Katalog-Check kann an genau eine
  Instanz seines Moduls gebunden sein, und Checks auf
  Loopback- oder Unit-Ziele waehlen unter mehreren Ports den, auf dem der Host laut letztem Scan lauscht.

### Fixed

- **Monitoring: einteilige vHost-Namen:** ein vHost-Name ohne Punkt (etwa `intranet`) bekommt keinen zentralen Check
  mehr; er loest nur ueber die Suchdomaene des Hosts auf.
