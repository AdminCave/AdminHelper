### Changed

- **Desktop: Gesamtfrist fuer grosse Antworten:** Den Abruf von Verbindungsliste, Tunnel-Liste und Playbook bricht
  die App ab, wenn die Antwort laenger als 120 s braucht; bisher hielt eine troepfelnde Antwort den Abruf beliebig
  lange offen.
- **Desktop: Tauri 2.12:** Die Desktop-App baut auf Tauri 2.12 und den passenden Plugins (Dialog 2.8, Notification
  2.8, Shell 2.6); die uebrigen Rust-Abhaengigkeiten sind auf ihren neuesten kompatiblen Stand gehoben.
- **Desktop: reqwest 0.13:** Der HTTP-Client der Desktop-App laeuft auf reqwest 0.13. Die Vertrauensanker bleiben
  gleich (Mozilla-Wurzeln fuer oeffentliche Zertifikate, TOFU-Pin und gepinnte CA wie bisher), die Kryptografie
  weiter auf ring.
- **Desktop: keyring 4:** Unter Linux und macOS spricht die App den Schluesselbund ueber keyring-core und die
  Store-Crates von keyring 4 an. Gespeicherte Passwoerter, Geraete-Identitaet und TOFU-Pins bleiben unter denselben
  Eintraegen lesbar; die Verbindung zum Secret Service entsteht weiter je Zugriff.
