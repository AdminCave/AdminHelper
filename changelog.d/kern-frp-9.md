### Fixed

- **Audit: Tunnel-Update mit verknuepfter Verbindung:** Wechselt ein Tunnel-Update Protokoll oder Typ und zieht die
  verknuepfte Verbindung nach, schreibt der Server zusaetzlich einen Eintrag `connection.updated` fuer die
  Verbindung; `detail` nennt den ausloesenden Tunnel.
