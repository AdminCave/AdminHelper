### Fixed

- **Agent-RPM: keine Scriptlet-Fehlermeldung ohne systemd:** in Containern ohne systemd als PID 1 meldeten rpm und dnf
  bei Installation und Entfernen „scriptlet failed“; `systemctl daemon-reload` scheitert dort jetzt still wie die
  uebrigen systemctl-Aufrufe des Pakets.
