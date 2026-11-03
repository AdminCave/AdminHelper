### Fixed

- **Server: Benachrichtigungs-Stream endet mit dem Ablauf des Client-Zertifikats:** ein offener Stream prueft bei
  seiner minuetlichen Neupruefung auch, ob das mTLS-Zertifikat noch gueltig ist, und endet nach dessen Ablauf.
