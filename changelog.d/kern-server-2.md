### Security

- **Server: Anmeldung unter MTLS_ENFORCE nur mit Client-Zertifikat:** Login, Token-Refresh und Bootstrap verlangen
  unter `MTLS_ENFORCE=true` (Standard) jetzt auch serverseitig ein vom Gateway geprueftes Client-Zertifikat und
  antworten sonst mit `403`. Clients ueber das Gateway sind nicht betroffen; ein Bootstrap von Hand braucht wie bisher
  `MTLS_ENFORCE=false`.
