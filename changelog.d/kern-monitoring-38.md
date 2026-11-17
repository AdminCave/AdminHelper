### Added

- **Monitoring Samba AD DC: neue Checks fuer smbd, nmbd oder winbind neben dem DC und fuer die SRV-Eintraege der
  Domaene;** der einzige DC einer Domaene meldet bei der Replikation jetzt ok statt unknown (ab Agent 0.47.0), die
  Karte zeigt die Zahl der Partner.
- **Monitoring Wiki.js: Wiki.js 3 (Image-Tag `3` oder `3.*`) bekommt den Check `/_ready`;** alles ausser 200 ist
  kritisch.
- **Monitoring: neues Modul edulution:** die Container der Plattform aus dem Compose-Projekt des Installers und die
  Gesundheitsroute der API.

### Changed

- **Monitoring ONLYOFFICE: die Karte zeigt beim Gesundheitscheck, ob die Antwort passt:** statt des Statuscodes steht
  dort `body_match`; kritisch ist der Check auch bei 200, wenn `/healthcheck` nicht `true` antwortet.
