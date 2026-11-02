### Fixed

- **Token-Refresh ohne Client-Zertifikat:** unter `MTLS_ENFORCE=true` zaehlt ein so abgewiesener Refresh wie ein
  fehlgeschlagener Login gegen das Login-Rate-Limit je IP; darueber antwortet `/api/auth/refresh` mit `429`.
- **FRP-Bulk-ZIP und `create-admin` mit Altnamen:** das Bulk-ZIP laesst Server- und Benutzernamen aus Altzeilen aus,
  die die API heute nicht mehr als Namen annimmt (mit einer Warnung im Log); `python -m app.cli create-admin` prueft
  den Benutzernamen wie die API (3 bis 64 Zeichen, Buchstaben, Ziffern, `.`, `_`, `-`).
