### Added

- **Monitoring: Netz-Freigaben als Modul `net_share`:** die Erkennung meldet jeden eingehaengten nfs-, nfs4-, cifs-
  und smb3-Mount eines Linux-Hosts als Fund (nur Mountpunkt und Typ, nie die Quelle). Ein uebernommener Fund prueft
  alle 5 Minuten, ob die Freigabe eingehaengt ist, ob sie haengt (`statfs` antwortet nicht in 10 s) und wie voll sie
  ist: critical bei fehlender oder haengender Freigabe und ab 95 % belegt, warning ab 85 %.

### Changed

- **Agent: Netz-Mounts nicht mehr in der Plattenliste:** unter Linux misst der Platten-Collector nfs-, nfs4-, cifs- und
  smb3-Mounts nicht mehr, eine haengende Freigabe haelt den Agent-Lauf nicht mehr an. Die Verlaufsdaten bleiben.
- **Monitoring: RDAP-Abfrage:** eine Abfrage samt Weiterleitungen und weiteren Servern endet jetzt innerhalb einer
  gemeinsamen Frist von 60 s.

### Fixed

- **Monitoring: Erkennung meldet verschwundene Instanzen auch bei unvollstaendigem Scan:** der Agent meldet je
  Abschnitt (Units, Container, Sockets, Marker, vHosts, Ports, Freigaben), ob er vollstaendig ist. Eine Instanz wird
  `gone`, wenn der Abschnitt, aus dem sie stammt, zweimal vollstaendig ohne sie war; ein Host, dessen Scan stets an
  einer anderen Stelle abgeschnitten wird, meldet so wieder `gone`. Aeltere Agents verhalten sich wie bisher.
