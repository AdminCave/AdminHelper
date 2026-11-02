### Fixed

- **Token-Refresh ohne Client-Zertifikat:** unter `MTLS_ENFORCE=true` zaehlt ein so abgewiesener Refresh wie ein
  fehlgeschlagener Login gegen das Login-Rate-Limit je IP; darueber antwortet `/api/auth/refresh` mit `429`.
