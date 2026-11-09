### Fixed

- **Ansible erreicht Server wie Verbinden:** das Inventory (jetzt JSON, `inventory.json`) schickt Ansible zu
  Adresse, Port, Benutzer, Schluessel und Sprung-Host der SSH-Verbindung des Servers, auch durch einen FRP-Tunnel.
  Bei mehreren SSH-Verbindungen waehlt man je Server, ohne Verbindung bleibt es beim Hostnamen (in den Zielen
  markiert). Laeuft der Tunnel-Visitor nicht, startet der Lauf nicht.
- **Ansible fragt das SSH-Passwort ab:** nutzt eine Verbindung Passwort-Anmeldung, startet der Lauf mit
  `--ask-pass`; Ansible fragt einmal im Terminal, ein Passwort fuer alle Server des Laufs (je nach Ansible-Version
  wird `sshpass` gebraucht).
