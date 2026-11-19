### Security

- **Gateway: interne Dienst-Routen nur im Compose-Netz:** Der Gateway beantwortet `/api/internal` auf `:443` jetzt
  selbst mit 404 und reicht die Pfade nicht mehr an den Server weiter. Die Dienste erreichen die Routen wie bisher
  direkt.
