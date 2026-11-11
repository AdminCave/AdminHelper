### Changed

- **Agent (FreeBSD): Swap und Load je CPU:** der FreeBSD-Agent meldet die Zahl der logischen CPUs und den Swap; das
  Monitoring bewertet dort jetzt Swap und Load je CPU wie unter Linux.
- **Agent (FreeBSD): eigene frpc-Logdatei:** frpc schreibt seine Ausgabe nicht mehr ins syslog, sondern nach
  `/var/log/adminhelper/frpc.log` (0600); das Paket bringt dafuer einen newsyslog-Eintrag zur Rotation mit.
