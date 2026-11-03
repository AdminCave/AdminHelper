### Fixed

- **Server: Benachrichtigungs-Stream endet mit dem Ablauf des Client-Zertifikats:** ein offener Stream prüft bei
  seiner minütlichen Neuprüfung auch, ob das mTLS-Zertifikat noch gültig ist, und endet nach dessen Ablauf.
