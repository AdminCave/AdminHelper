### Security

- **Datenbank-Rollen enger:** Keine Dienst-Rolle verbindet sich mehr mit `template1`; der Scheduler liest
  `alembic_version`, aendert sie aber nicht; der `ca-issuer` aendert in `enrollment_tokens` und `device_lines` nur
  die Spalten, die er setzt (`used_at`, `revoked_at`, `revoked_reason`). Der naechste Start setzt die Rechte.
