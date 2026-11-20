### Fixed

- **Web: das Favicon laedt wieder:** `public/logo.svg` war kein wohlgeformtes XML (ein `<` im CSS-Kommentar), der Browser verwarf die ganze Datei; ein Test parst sie jetzt als XML.
