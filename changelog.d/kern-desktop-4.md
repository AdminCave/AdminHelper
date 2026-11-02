### Changed

- **Desktop: Gesamtfrist fuer grosse Antworten:** Den Abruf von Verbindungsliste, Tunnel-Liste und Playbook bricht
  die App ab, wenn die Antwort laenger als 120 s braucht; bisher hielt eine troepfelnde Antwort den Abruf beliebig
  lange offen.
- **Desktop: Tauri 2.12:** Die Desktop-App baut auf Tauri 2.12 und den passenden Plugins (Dialog 2.8, Notification
  2.8, Shell 2.6); die uebrigen Rust-Abhaengigkeiten sind auf ihren neuesten kompatiblen Stand gehoben.
