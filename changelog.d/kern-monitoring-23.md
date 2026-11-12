### Fixed

- **Monitoring: keine Fehlalarme mehr auf den frps-Ports:** ein Port, der nach gelungenem Verbindungsaufbau ohne
  erkennbares Protokoll schliesst, gilt als erreichbar (`unknown`, nach TLS `tls`); critical bleibt ein Port, dessen
  Verbindungsaufbau scheitert. Das neue Katalog-Modul `frps` erkennt den frps-Container und prueft, ob er laeuft;
  seine Ports werden nicht mehr als einzelne Ports geprobt, und frps schreibt dazu keine Warnungen mehr ins Log.
  Bereits uebernommene Port-Instanzen der frps-Ports werden ein Fund `gone`.
