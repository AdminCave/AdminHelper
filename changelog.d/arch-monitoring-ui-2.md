### Added

- **Desktop: Details hinter den Monitoring-Checks:** die ausgeklappte Zeile eines Checks nennt, was hinter seinen
  Zahlen steht. Systemzustand: die Pakete mit offenen Sicherheits-Updates, die Pakete, die einen Neustart verlangen,
  und nach einem OOM-Kill die beendeten Prozesse mit Name und PID; der Reiter „Updates & Neustarts“ bekommt die
  Spalte „Pakete“. Docker: Container nach Compose-Projekt gruppiert, mit veroeffentlichten Ports und Laufzeit.
  Proxmox: je VM/CT Ablage, Groesse und Verifizierung des neuesten Backups, die Backup-Jobs und der letzte
  vzdump-Fehler, dazu Spalten im Reiter „Backups“. ZFS: Fragmentierung, letzter Scrub und die vdevs mit Fehlern.
  Nur Namen und Zahlen, nie eine Befehlsausgabe oder Befehlszeile, und nur im Desktop: Status, Meldung und Metriken
  der Checks bleiben unveraendert, Mail und Webhooks nennen keine Details.
- **Agent: Namen fuer die Details:** der Agent schickt die Paketnamen aus seiner Zaehlung (`apt-get -s`, `dnf -C`,
  `pkg audit -q`, `/var/run/reboot-required.pkgs`, `needs-restarting -r`), nach einem OOM-Kill Name und PID aus der
  Kernel-Meldung im Journal, die Compose-Labels, Ports und Startzeit aus `docker inspect`, die Backup-Jobs und den
  letzten gescheiterten vzdump-Lauf ueber `pvesh get` (nur lesend, mit dem Backup-Index hoechstens alle 30 min) und
  Scrub und vdev-Fehler aus `zpool status -j` (ab OpenZFS 2.3). Jeder neue Aufruf steht mit festen Argumenten auf
  der Befehls-Freigabeliste.
