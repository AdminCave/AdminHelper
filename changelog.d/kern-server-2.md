### Security

- **Server: Anmeldung unter MTLS_ENFORCE nur mit Client-Zertifikat:** Login, Token-Refresh und Bootstrap verlangen
  unter `MTLS_ENFORCE=true` (Standard) jetzt auch serverseitig ein vom Gateway geprueftes Client-Zertifikat und
  antworten sonst mit `403`. Clients ueber das Gateway sind nicht betroffen; ein Bootstrap von Hand braucht wie bisher
  `MTLS_ENFORCE=false`.
- **Server: Hoechstdauer einer Web-Sitzung:** Der Server beendet eine Browser-Sitzung 24 Stunden nach der Anmeldung,
  auch bei laufender Bedienung; danach ist eine neue Anmeldung noetig. `WEB_SESSION_MAX_HOURS` stellt die Dauer ein,
  `0` schaltet ab. Desktop, CLI und Skripte sind nicht betroffen.
