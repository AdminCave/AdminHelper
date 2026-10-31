### Changed

- **Server-CLI: `--password` zusammen mit `--password-stdin` wird abgelehnt:** `create-admin` und `reset-admin` brechen mit Exit 2 ab, statt das Passwort aus `--password` in der Prozess-argv zu lassen.
