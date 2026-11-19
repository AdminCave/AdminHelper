### Fixed

- **Agent-Installation: `apt update` nach dem CA-Pinning:** `agent-install.sh` pinnte apt auf die CA unter
  `/etc/adminhelper/identity/`, die der apt-Benutzer `_apt` nicht lesen darf; danach scheiterte jedes `apt update`
  an der AdminHelper-Quelle. Der Installer legt jetzt eine lesbare Kopie `/etc/apt/adminhelper-ca.crt` an, der Agent
  haelt sie bei jeder Erneuerung aktuell. Bestandshosts: die Kopie von Hand anlegen und `CAInfo` darauf
  stellen (zwei Befehle, Doku Agent-Rollout); ein erneuter Lauf von `agent-install.sh` ohne `--server-id` pinnt
  nicht.

### Changed

- **Agent-Paket: smartmontools nur noch vorgeschlagen:** deb und rpm nennen `smartmontools` als `Suggests` statt
  `Recommends`, es kommt also nicht mehr ungefragt auf VMs und in Container. `agent-install.sh` installiert es nur
  auf physischer Hardware (`systemd-detect-virt` meldet `none`).
