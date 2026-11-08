### Changed

- **Desktop: eingebettetes RDP folgt den Verbindungsoptionen:** `nla: false` startet die eingebettete Sitzung ohne
  CredSSP wie den RDP-Client des Betriebssystems; eine Verbindung mit RD-Gateway oder Druckern lehnt sie mit
  `ERR_RDP_OS_CLIENT` ab, damit der Aufrufer den Client des Betriebssystems startet.
