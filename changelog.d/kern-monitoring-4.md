### Fixed

- **Monitoring-Verlauf und Server-Vergleich zeigen die neuesten Werte (R-1104):** der Zeitraum endete am letzten
  vollen Rasterschritt, die juengsten Daten fehlten bis zu einem Schritt (15 min bei 24 Std., 6 h bei 30 Tagen).
  Er endet jetzt am ersten Rasterpunkt ab jetzt.
- **Monitoring-API: Abfrage der Standard-Template-Aktualisierung (R-1107):** `GET /templates/{id}/builtin-update`
  antwortete fuer die Template-IDs `assignments` und `suggestions` mit der Zuweisungs- bzw. Vorschlagsliste `[]`
  statt mit seiner eigenen Antwort. Die Route ist jetzt vor diesen beiden registriert.
