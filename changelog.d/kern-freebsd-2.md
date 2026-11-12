### Changed

- **Agent (FreeBSD): Hinweis auf alte frpc-Zeilen im syslog:** fruehere Builds des FreeBSD-Agents schrieben die
  Ausgabe von frpc ins syslog (`/var/log/messages`, `/var/log/daemon.log`). Diese Zeilen und ihre Archive bleiben
  nach dem Upgrade dort, bis newsyslog sie herausrotiert; das Paket aendert fremde Systemlogs nicht. Die Doku
  (Agent-Deployment, Logs) nennt das.
