### Added

- **Agent unter Windows per Einzeiler:** `scripts/agent-install.ps1` installiert oder aktualisiert den Agent-Dienst
  aus dem neuesten Release, prüft Agent und frpc vorher gegen `SHA256SUMS` und provisioniert den Host mit
  `-ServerId`; den Token fragt es verdeckt ab und gibt ihn über stdin weiter (R-1578).
