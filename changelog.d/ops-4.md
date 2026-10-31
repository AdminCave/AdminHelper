### Fixed

- **Diagnose: `.env` wie compose gelesen:** `env.sanitized` im Diagnose-Bundle und die Masken der Logs zerlegen die
  `.env` jetzt so, wie Docker Compose sie liest. Ein Wert in Anfuehrungszeichen, der ueber mehrere Zeilen laeuft,
  konnte bisher den Wert eines geheimen Schluessels dahinter unmaskiert lassen.
- **Diagnose: Geheimnis an einem Token ganz maskiert:** Stand ein Wert aus der `.env` ohne Trenner an einem oder in
  einem Token (Bearer, JWT, Provisioning-Token), konnte die Maske einen Rest des Werts oder des Tokens in den Logs
  stehen lassen. Wert und Token werden jetzt als ein Stueck maskiert.
