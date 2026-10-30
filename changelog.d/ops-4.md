### Fixed

- **Diagnose: `.env` wie compose gelesen:** `env.sanitized` im Diagnose-Bundle und die Masken der Logs zerlegen die
  `.env` jetzt so, wie Docker Compose sie liest. Ein Wert in Anführungszeichen, der über mehrere Zeilen läuft,
  konnte bisher den Wert eines geheimen Schlüssels dahinter unmaskiert lassen.
