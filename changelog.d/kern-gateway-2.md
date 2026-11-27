### Changed

- **Webhooks unter erzwungenem mTLS:** Webhook-Trigger (`POST /api/hooks/trigger`, auch mit dem Token im Pfad) kommen
  ohne Client-Zertifikat ueber die Enrollment-Plane `:8444` an, mit eigenem Ratelimit und hoechstens 1 MiB Body. Die
  Antworten beim Anlegen und Erneuern eines Webhook-Tokens nennen den Port in `trigger_port`; das curl-Beispiel im
  Web-Dialog zeigt dorthin.
