### Changed

- **Desktop: eingebettete RDP-Sitzung ohne Anzeige endet:** Zeigt 60 s lang kein Fenster und kein Tab eine
  eingebettete RDP-Sitzung, endet sie wie nach `rdp_session_stop`. Abdocken und Tabwechsel halten die Sitzung.
- **Desktop: eingebettetes RDP folgt keiner Server-Umleitung:** Der eingebaute RDP-Client verbindet sich nur mit
  dem gewaehlten Ziel; eine Umleitung durch den Server beendet die Sitzung mit `redirect`. Die App schreibt keine
  TLS-Sitzungsschluessel, auch wenn `SSLKEYLOGFILE` gesetzt ist. IronRDP-Fork auf `b3e9f580`. Doku:
  Desktop-Entwicklerdoku (DE+EN).
