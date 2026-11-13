### Fixed

- **Agent unter FreeBSD: Proben auf eigene Adressen scheiterten:** der Agent las die Liste der lauschenden Sockets
  nicht, sobald darin eine noch ungebundene Socket stand (etwa seine eigene waehrend einer Probe), und wies jede
  Probe auf eine Adresse des eigenen Hosts ab.
