### Fixed

- **Diagnose: `.env` wie compose gelesen:** `env.sanitized` im Diagnose-Bundle und die Masken der Logs zerlegen die
  `.env` jetzt so, wie Docker Compose sie liest. Ein Wert in Anführungszeichen, der über mehrere Zeilen läuft,
  konnte bisher den Wert eines geheimen Schlüssels dahinter unmaskiert lassen.
- **Diagnose: Geheimnis an einem Token ganz maskiert:** Stand ein Wert aus der `.env` ohne Trenner an einem oder in
  einem Token (Bearer, JWT, Provisioning-Token), konnte die Maske einen Rest des Werts oder des Tokens in den Logs
  stehen lassen. Wert und Token werden jetzt als ein Stück maskiert.
