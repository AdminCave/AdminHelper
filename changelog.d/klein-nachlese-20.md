### Fixed

- **Server und Monitoring: Port ueber 65535:** Eine Port-Einstellung ueber 65535 (etwa `SMTP_PORT`, `FRP_BIND_PORT`, `ENROLL_PORT`) stoppt den Start jetzt mit einer klaren Meldung, statt erst beim Verbinden zu scheitern.
