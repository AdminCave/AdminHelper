### Changed

- **Server: Servernamen auch als Windows-Ordner gueltig:** ein neuer oder umbenannter Server darf weder `:` noch
  einen unter Windows reservierten Geraetenamen (`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`, auch mit
  Endung) tragen; die API antwortet dann mit `422`. Bestehende Namen bleiben gueltig und werden im FRP-Bulk-ZIP
  weiter ausgeliefert.
