### Fixed

- **Desktop: Ansible-Lauf im Tab beim Beenden:** Wird die App waehrend eines Playbook-Laufs im Tab beendet, bleiben
  Inventory und Playbook des Laufs nicht mehr im Temp-Verzeichnis liegen.
- **Desktop: SFTP-Download unter Windows:** Der Speichern-Dialog schlaegt keinen Namen mehr vor, den Windows
  ablehnt (Zeichen wie `?` oder `*`, Punkt oder Leerzeichen am Ende, Geraetenamen wie `NUL.txt`).
- **Desktop: RDP im Tab im Sitzungsverlauf:** Eine RDP-Sitzung im Tab endet im Verlauf, sobald der Tab die Sitzung
  beendet zeigt oder geschlossen wird, wie bei SSH.
