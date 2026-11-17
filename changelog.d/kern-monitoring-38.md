### Changed

- **Monitoring ONLYOFFICE: die Karte zeigt beim Gesundheitscheck, ob die Antwort passt:** statt des Statuscodes steht
  dort `body_match`; kritisch ist der Check auch bei 200, wenn `/healthcheck` nicht `true` antwortet.
