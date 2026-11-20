### Added

- **Windows-Agent: automatisches Update:** der Agent-Dienst sieht einmal am Tag nach einem neueren Release, laedt Agent
  und frpc ueber die Repo-Ebene des Servers (`:8445/windows/`), prueft die minisign-Signatur samt Version und
  installiert sich; beendet der neue Dienst binnen 15 Minuten keinen Durchlauf, kehrt er zum alten Stand zurueck.
  Abschalten mit `AUTO_UPDATE="0"` in `adminhelper.conf`. Der Release baut dafuer den signierten Update-Satz.
