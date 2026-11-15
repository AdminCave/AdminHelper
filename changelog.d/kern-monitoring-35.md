### Added

- **Monitoring: WP-Cron im Modul WordPress:** Der neue Check `cron` zaehlt alle 15 Minuten die geplanten Ereignisse
  einer WordPress-Site im Docker-Container, die ueberfaelligen und das Alter des aeltesten. Wartet ein Ereignis
  laenger als eine Stunde, warnt der Check, nach einem Tag ist er kritisch. Der Agent liest die Option `cron` mit
  einer festen, nur lesenden Abfrage, und zwar nur ueber das Unix-Socket des Datenbank-Containers auf demselben
  Host. Benutzer und Passwort nimmt er aus der Umgebung des WordPress-Containers. Sie verlassen den Host nie, zum
  Server gehen nur die drei Zahlen. Doku: Monitoring, Abschnitt App-Module, und Entwickler-Doku Agent (DE+EN).
