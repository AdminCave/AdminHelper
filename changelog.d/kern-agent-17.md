### Fixed

- **Agent-DEB: Paketskripte brechen ohne systemd nicht mehr ab:** Installation, Upgrade und Entfernen scheitern in
  Containern und chroots ohne systemd als PID 1 nicht mehr; ein fehlgeschlagenes `systemctl daemon-reload` wird still
  uebergangen wie im RPM-Paket.
